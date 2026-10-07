# -*- coding: utf-8 -*-
"""
Discord bot for analyzing Stable Diffusion image generation parameters.

@author: seesthenight & Circle D5
"""

import os
import re
import io
import math
import time
import pprint
import logging
from typing import Optional, Tuple, Dict, Any, Callable

import discord
from discord.ext import commands
from discord import File, Embed, Interaction, Attachment, app_commands
from dotenv import load_dotenv
from PIL import Image

from module.MechaHassakuException import MechaHassakuError
from module.parser import parse_generation_parameters, parse_novelai_parameters
from module.metadata import has_parameters, read_image_metadata

# Goes to the root logger that discord.py sets up in client.run (journald on the VM).
# Never log prompt contents.
log = logging.getLogger("mechahassaku")


# ==================== Configuration ====================
AUTO_CHANNEL_NAME = '🤖│prompts-auto-share'
EMBED_FIELD_LIMIT = 1000
BOT_LOG_CHANNEL_ID = 1120267966731259984
BOT_STATUS = "Type /help to see how I work"

# Channels on the AI Art & Models Hub server, linked from /help
AUTO_SHARE_CHANNEL_ID = 1120359493142843522
HELP_CHANNEL_ID = 1072336225496739970
RULES_CHANNEL_ID = 1094982199528394823
COLOR_ROLES_CHANNEL_ID = 1110212451254935563
HELPFUL_LINKS_CHANNEL_ID = 1081221623597781153

# https://discord.com/channels/<guild or @me>/<channel>/<message> (also canary./ptb./discordapp.com)
RE_MESSAGE_LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+|@me)/(\d+)/(\d+)")

CIVITAI_URL = "https://civitai.com/user/Ikena/models"
SUBSCRIBESTAR_URL = "https://subscribestar.adult/citrus-models"
SEAART_URL = "https://www.seaart.ai/ja/user/Ikena"

# Tools page links (checked 2026-10-08; Stability Matrix lists the original Forge as legacy)
STABILITY_MATRIX_URL = "https://github.com/LykosAI/StabilityMatrix"
STABILITY_MATRIX_INSTALL_URL = (
    "https://github.com/LykosAI/StabilityMatrix/blob/main/docs/getting-started/installation.md"
)
FORGE_NEO_URL = "https://github.com/Haoming02/sd-webui-forge-classic/tree/neo"
COMFYUI_URL = "https://github.com/Comfy-Org/ComfyUI"
VLCAPTIONER_URL = "https://github.com/Ikena1992/VLCaptioner"
KOHYA_URL = "https://github.com/bmaltais/kohya_ss"

# File paths
ASSET_SORRY = "./assets/mecha_sorry.png"
ASSET_CONFUSED = "./assets/mecha_confused.png"


class MechaHassakuBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Register slash commands with Discord. Runs once per process start, i.e. on each deploy.
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception as e:
            log.error("Error syncing slash commands: %s", e)


# Bot setup
intents = discord.Intents.all()
intents.message_content = True
client = MechaHassakuBot(command_prefix='$', intents=intents)


# ==================== Bot Events ====================
@client.event
async def on_ready() -> None:
    """Initialize bot on startup."""
    await client.change_presence(activity=discord.CustomActivity(name=BOT_STATUS))

    log.info("Online as %s", client.user)


@client.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages."""
    if message.author == client.user:
        return

    # "@MechaHassaku how do I use you?" -> point to /help
    if client.user in message.mentions and message.reference is None and not message.attachments:
        await message.reply(
            f"Hi! Type `/help` to see what I can do, or post an image in <#{AUTO_SHARE_CHANNEL_ID}> "
            "and I'll show its prompt.",
            mention_author=False
        )
        return

    await model_request_detector(message)
    
    # Auto-analyze images in specific channel
    if str(message.channel) != AUTO_CHANNEL_NAME or not message.attachments:
        return
    
    start_time = time.time()
    await analyze_all_attachments(message)
    log.info("Auto-share analysis took %.2fs", time.time() - start_time)


# ==================== Embed Creation ====================
EMBED_TOTAL_LIMIT = 6000    # Discord limit for all text in one embed
EMBED_MAX_FIELDS = 25
THUMBNAIL_SIZE = (512, 512)
THUMBNAIL_NAME = "thumbnail.png"
# When an embed is too long, prompts are cut to these lengths in turn
PROMPT_CUT_STEPS = (3000, 2000, 1200, 600, 300)
CUT_NOTE = "\n… (cut — full text in fullParameters.txt)"


def _add_field(embed: Embed, name: str, value: Any, inline: bool = True) -> None:
    """Add a field unless the value is empty (Discord rejects empty field values)."""
    if value is None:
        return
    text = str(value)
    if text.strip():
        embed.add_field(name=name, value=text, inline=inline)


def add_big_field(embed: Embed, name: str, txt: Any, inline: bool = False) -> None:
    """Add a field to embed, splitting into multiple fields if text exceeds limit."""
    txt = "" if txt is None else str(txt)
    if not txt.strip():
        return
    if len(txt) < EMBED_FIELD_LIMIT:
        embed.add_field(name=name, value=txt, inline=inline)
    else:
        chunks = math.ceil(len(txt) / EMBED_FIELD_LIMIT)
        for i in range(chunks):
            start = i * EMBED_FIELD_LIMIT
            end = (i + 1) * EMBED_FIELD_LIMIT
            text_value = txt[start:end]
            embed.add_field(name=f"{name}({i})", value=text_value, inline=inline)


def _cut(text: Any, limit: Optional[int]) -> Any:
    if limit is None or not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + CUT_NOTE


def _fits(embed: Embed) -> bool:
    return len(embed) <= EMBED_TOTAL_LIMIT and len(embed.fields) <= EMBED_MAX_FIELDS


def create_pnginfo_view(pnginfo_kv: Dict[str, Any], thumbnail: Optional[File] = None) -> Embed:
    """Create an embed displaying generation parameters.

    Long prompts are cut step by step until the embed fits Discord's limits;
    the full text is always in the attached fullParameters.txt.
    """
    tags = _detect_tags(pnginfo_kv)
    title_tags = "   ".join(f"` {tag} `" for tag in tags) if tags else "FAILED TO GET TAGS"

    for prompt_limit in (None,) + PROMPT_CUT_STEPS:
        embed = Embed(
            title=f"Image Prompt & Settings :tools:\n{title_tags}",
            color=0x7101fa
        )
        if pnginfo_kv.get("ui_type") != "comfyui":
            _add_prompt_fields(embed, pnginfo_kv, prompt_limit)
            _add_generation_fields(embed, pnginfo_kv)
            _add_hires_fields(embed, pnginfo_kv)
            _add_model_fields(embed, pnginfo_kv, prompt_limit)
        else:
            embed.description = "ComfyUI workflow detected. Full metadata attached below :arrow_double_down:"
        if _fits(embed):
            break

    if thumbnail is not None:
        embed.set_thumbnail(url=f"attachment://{thumbnail.filename}")
    return embed


def make_thumbnail(image: Image.Image) -> File:
    """Small PNG copy of the image for the embed thumbnail, built in memory."""
    thumb = image.copy()
    thumb.thumbnail(THUMBNAIL_SIZE)
    if thumb.mode not in ("RGB", "RGBA"):
        thumb = thumb.convert("RGBA")
    buf = io.BytesIO()
    thumb.save(buf, "PNG")
    buf.seek(0)
    return File(buf, filename=THUMBNAIL_NAME)


# Anima: Cosmos-based anime model using a Qwen3 0.6B text encoder and the Qwen-Image VAE.
# Forge Neo records those as "Module N: qwen_3_06b_..." / "qwen_image_vae".
RE_ANIMA_TEXT_ENCODER = re.compile(r"qwen_?3_?0\.?6b", re.IGNORECASE)
# "anima" in a model name, but not other model families that start the same way
RE_ANIMA_MODEL_NAME = re.compile(r"anima(?!gine|pencil|te)", re.IGNORECASE)


def _is_anima(kv: Dict[str, Any]) -> bool:
    modules = " ".join(str(v) for k, v in kv.items() if k.startswith("Module"))
    return bool(RE_ANIMA_TEXT_ENCODER.search(modules) or RE_ANIMA_MODEL_NAME.search(str(kv.get('Model', ''))))


def _detect_tags(pnginfo_kv: Dict[str, Any]) -> list[str]:
    """Detect and return tags based on image metadata."""
    tags = []

    # Detect UI type
    prompt_val = str(pnginfo_kv.get('Prompt', ''))

    if 'sui_image_params' in prompt_val or 'SwarmUI version' in pnginfo_kv:
        tags.append('SWARM UI')
    elif 'ComfyUI AI Params' in pnginfo_kv:
        tags.append('COMFY UI')
    elif 'Novel AI Params' in pnginfo_kv:
        tags.append('NOVEL AI')
    elif 'Prompt' in pnginfo_kv:
        tags.append('WEBUI')

    # Parameters were read from the pixels (alpha / RGB LSBs), not from text chunks
    if 'Stealth' in pnginfo_kv:
        tags.append('STEALTH')

    # Detect model type
    model = str(pnginfo_kv.get('Model', '')).lower()
    if _is_anima(pnginfo_kv):
        tags.append('ANIMA')
    elif model:
        if any(keyword in model for keyword in ['illustrious', 'noob', 'wai']):
            tags.append('ILLUSTRIOUS')
        elif 'xl' in model or 'sdxl' in model:
            tags.append('SDXL')
        elif 'pony' in model:
            tags.append('PONY')
        elif 'flux' in model:
            tags.append('FLUX')

    # Detect LoRA type
    prompt = prompt_val.lower()
    if 'lora' in prompt or '<lora:' in prompt or 'LoRAs' in pnginfo_kv:
        tags.append('LORA')
    elif 'locon' in prompt:
        tags.append('LOCON')
    elif 'loha' in prompt:
        tags.append('LOHA')

    # Detect upscaling
    if 'Hires upscaler' in pnginfo_kv or 'Refiner steps' in pnginfo_kv:
        tags.append('HIRES')

    return tags



def _add_prompt_fields(embed: Embed, kv: Dict[str, Any], limit: Optional[int] = None) -> None:
    """Add prompt-related fields to embed."""
    add_big_field(embed, '__Prompt__ :keyboard:', _cut(kv.get('Prompt'), limit), False)
    add_big_field(embed, '__Negative Prompt__ :no_entry_sign:', _cut(kv.get('Negative prompt'), limit), False)


def _add_generation_fields(embed: Embed, kv: Dict[str, Any]) -> None:
    """Add generation parameter fields to embed."""
    fields = [
        ('Seed', '__Seed__ :game_die:', True),
        ('Sampler', '__Sampler__ :cyclone:', True),
        ('CFG scale', '__CFG Scale__ :level_slider:', True),
        ('Steps', '__Steps__ :person_walking:', True),
        ('Clip skip', '__Clip Skip__ :paperclip:', True),
    ]

    for key, name, inline in fields:
        _add_field(embed, name, kv.get(key), inline)
    # Add scheduler if present (SwarmUI/ComfyUI)
    if kv.get('Schedule type') != 'Automatic':
        _add_field(embed, '__Scheduler__ :calendar:', kv.get('Schedule type'))
    # Image size (special handling)
    if kv.get('Size-1') and kv.get('Size-2'):
        _add_field(embed, '__Image Size__ :straight_ruler:', f"{kv['Size-1']}x{kv['Size-2']}")


def _add_hires_fields(embed: Embed, kv: Dict[str, Any]) -> None:
    """Add hires fix fields to embed."""
    if not kv.get('Hires upscaler'):
        return

    _add_field(embed, '__Hires. Upscaler__ :arrow_double_up:', kv.get('Hires upscaler'))
    _add_field(embed, '__Hires. Upscale__ :eight_spoked_asterisk:', kv.get('Hires upscale'))
    _add_field(embed, '__Denoising Strength__ :muscle:', kv.get('Denoising strength'))


def _add_model_fields(embed: Embed, kv: Dict[str, Any], limit: Optional[int] = None) -> None:
    """Add model-related fields to embed."""
    model = kv.get('Model')
    if model:
        is_xl = any(tag in str(model).upper() for tag in ['XL', 'SDXL'])
        name = '__Model__ :regional_indicator_x::regional_indicator_l:' if is_xl else '__Model__ :art:'
        _add_field(embed, name, model)

    _add_field(embed, '__Model Hash__ :key:', kv.get('Model hash'))
    _add_field(embed, '__VAE__ :file_folder:', kv.get('VAE'))

    # Add LoRAs if present (ComfyUI specific)
    add_big_field(embed, '__LoRAs__ :jigsaw:', _cut(kv.get('LoRAs'), limit), inline=False)



# ==================== Image Analysis ====================
async def analyze_attachment_and_reply(
    attachment: Attachment,
    response_destination: Callable,
    ephemeral: bool = False
) -> None:
    """Analyze a single image attachment and reply with parameters. Nothing is written to disk."""
    if not attachment.content_type or not attachment.content_type.startswith("image"):
        return

    try:
        downloaded_byte = await attachment.read()

        with io.BytesIO(downloaded_byte) as image_data:
            with Image.open(image_data) as image:
                # Text chunks first; hidden pixel data (stealth pnginfo) only when they have nothing
                data, stealth = read_image_metadata(image)

                # Check if parameters exist
                if not has_parameters(data):
                    await response_destination("No parameters detected. Upload the image instead of pasting it.")
                    return

                # Parse parameters based on UI type
                ed = _parse_parameters(data)
                if stealth:
                    ed["Stealth"] = stealth.describe()

                thumbnail = make_thumbnail(image)

        log.info("Analyzed %s (%s%s)", attachment.filename, ed.get("ui_type"), ", stealth" if stealth else "")

        # Full parameters as an attachment, built in memory
        text_file = File(
            io.BytesIO(pprint.pformat(data, indent=4).encode("utf-8")), filename="fullParameters.txt"
        )
        embed = create_pnginfo_view(ed, thumbnail)

        if ephemeral:
            await response_destination(embed=embed, file=thumbnail, ephemeral=ephemeral)
            await response_destination(file=text_file, ephemeral=ephemeral)
        else:
            await response_destination(embed=embed, file=thumbnail)
            await response_destination(file=text_file)

    except Exception as err:
        log.exception("Failed to analyze %s", attachment.filename)
        _handle_analysis_error(err, response_destination)


def _parse_parameters(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse generation parameters from image metadata."""
    ed = {}

    # WebUI format
    if "parameters" in data:
        ed = parse_generation_parameters(data["parameters"])
        ed["ui_type"] = "webui"

    # ComfyUI format
    elif "prompt" in data:
        ed["ui_type"] = "comfyui"
        ed["ComfyUI AI Params"] = data["prompt"]
        # Minimal fields for embed
        ed["Prompt"] = "ComfyUI workflow detected. Full metadata attached below :arrow_double_down: "

    # Novel AI format
    elif "Comment" in data:
        ed = parse_novelai_parameters(data)
        ed["Novel AI Params"] = True
        ed["ui_type"] = "novelai"

    return ed



def _handle_analysis_error(err: Exception, response_destination: Callable) -> None:
    """Handle errors during image analysis."""
    error_messages = {
        KeyError: ">>> > Sorry, but I couldn't retrieve parameters from the shared image; it seems the EXIF data is either missing or in an incorrect format.",
        AttributeError: ">>> > Sorry, the linked message is too old for me to access.",
    }

    message = error_messages.get(type(err), ">>> > Some error due to my stupid masters' incompetence.")

    sorry_image = File(ASSET_SORRY)
    raise MechaHassakuError(message, sorry_image) from None


async def analyze_all_attachments(message: discord.Message) -> None:
    """Analyze all image attachments in a message."""
    for attachment in message.attachments:
        if not attachment.content_type or not attachment.content_type.startswith("image"):
            continue

        msg = await message.reply("Analyzing image >>> <a:kururing:1113757022257696798> ", mention_author=False)

        try:
            await analyze_attachment_and_reply(attachment, message.channel.send)
            await msg.delete()
        except MechaHassakuError as err:
            await msg.delete()
            await msg.channel.send(err.message, file=err.file)


# ==================== Model Request Detection ====================
RE_MODEL_QUESTION = re.compile(
    r"(which\s+one|which\s+model|the\s+model|what\s+model|model\s+pls|model\s+please)",
    re.IGNORECASE
)


async def model_request_detector(message: discord.Message) -> None:
    """Detect a reply asking which model an image used, and answer it."""
    if message.reference is None or not RE_MODEL_QUESTION.search(message.content):
        return

    try:
        referenced_message = await message.channel.fetch_message(message.reference.message_id)
        await model_request_handler(referenced_message, referenced_message.channel.send)
    except Exception:
        log.exception("Model request failed")


def model_answer(ed: Dict[str, Any]) -> Optional[str]:
    """Reply text for "which model?", or None when the image does not tell (e.g. ComfyUI)."""
    model = ed.get('Model')
    if ed.get('ui_type') == 'comfyui' or not model:
        return None
    hash_part = f" with the hash `{ed['Model hash']}`" if ed.get('Model hash') else ""
    return (
        f">>> The model used appears to be `{model}`{hash_part} according to the image's metadata.\n"
        "Tip: for all the settings, use /checkparameters with a link to the message containing this image!"
    )


async def model_request_handler(message: discord.Message, response_destination: Callable) -> None:
    """Answer which model the images in a message used (WebUI, SwarmUI, NovelAI, stealth)."""
    for attachment in message.attachments:
        if not attachment.content_type or not attachment.content_type.startswith("image"):
            continue

        msg = await message.reply("Taking a look....... <a:kururing:1113757022257696798> ")

        try:
            downloaded_byte = await attachment.read()
            with io.BytesIO(downloaded_byte) as image_data:
                with Image.open(image_data) as image:
                    data, _ = read_image_metadata(image)
            answer = model_answer(_parse_parameters(data)) if has_parameters(data) else None
            if answer:
                await response_destination(answer)
        except Exception:
            log.exception("Model request handler failed for %s", attachment.filename)
        finally:
            await msg.delete()


# ==================== Slash Commands ====================
@client.tree.command(name="ping", description="Check that the bot is awake and how fast it responds")
async def ping(interaction: Interaction) -> None:
    """Respond with bot latency."""
    latency_ms = round(client.latency * 1000)
    await interaction.response.send_message(
        f'>>> \U0001f3d3 Pong! Client Latency : `{latency_ms}ms`'
    )


async def _fetch_linked_message(link: str) -> discord.Message:
    """Fetch the message a Discord message link points to (channels and threads)."""
    match = RE_MESSAGE_LINK.search(link)
    if not match:
        raise ValueError("not a message link")
    channel_id, message_id = int(match.group(2)), int(match.group(3))
    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    return await channel.fetch_message(message_id)


@client.tree.command(
    name="checkparameters",
    description="Show the prompt and settings of an AI image (attach it, or paste a message link)"
)
@app_commands.describe(
    image="The image to check (upload the original file)",
    link="Link to a message with images (right-click the message → Copy Message Link)",
    private="Only you can see the result (default: off)",
)
async def checkparameters(
    interaction: Interaction,
    image: Optional[Attachment] = None,
    link: Optional[str] = None,
    private: bool = False,
) -> None:
    """Check parameters of an attached image or of the images in a linked message."""
    if image is None and not link:
        await interaction.response.send_message(
            "Attach an image with `image:` or paste a message link with `link:`. See `/help` for details.",
            ephemeral=True
        )
        return

    try:
        await interaction.response.defer(ephemeral=private)
        start_time = time.time()

        if image is not None:
            attachments = [image]
        else:
            try:
                message = await _fetch_linked_message(link)
            except ValueError:
                await interaction.followup.send(
                    "That doesn't look like a message link. Right-click the message → **Copy Message Link**.",
                    ephemeral=True
                )
                return
            attachments = message.attachments

        if not attachments:
            await interaction.followup.send(
                "There's nothing attached, you know<:TeriDerp:1104059514501746689>?",
                ephemeral=private
            )
            return

        for attachment in attachments:
            try:
                await analyze_attachment_and_reply(
                    attachment,
                    interaction.followup.send,
                    ephemeral=private
                )
            except MechaHassakuError as err:
                await interaction.followup.send(err.message, file=err.file, ephemeral=private)

        log.info("/checkparameters took %.2fs", time.time() - start_time)

    except Exception:
        log.exception("/checkparameters failed")
        await interaction.followup.send(
            ">>> > Some error due to my stupid masters' incompetence.",
            file=File(ASSET_SORRY),
            ephemeral=private
        )


@client.tree.command(
    name="anonsend",
    description="Post an image without showing your name (moderators can still see who sent it)"
)
@app_commands.describe(file="The image to post")
async def anonsend(interaction: Interaction, file: Attachment) -> None:
    """Send an image anonymously (re-encoded in memory, which also drops its metadata)."""
    try:
        user_id = interaction.user.id
        channel = await client.fetch_channel(BOT_LOG_CHANNEL_ID)

        download_byte = await file.read()
        with io.BytesIO(download_byte) as image_data:
            with Image.open(image_data) as image:
                buf = io.BytesIO()
                image.save(buf, "PNG")
                buf.seek(0)

                await client.fetch_channel(interaction.channel_id)
                afile = File(buf, filename="image.png")

                await interaction.response.send_message(
                    "Image sent anonymously!\n Only you can see this message :man_detective:",
                    ephemeral=True
                )

                m = await interaction.followup.send(file=afile)

                # Log for security
                await channel.send(
                    f"User ID {user_id} sent an image anonymously! Jump to message: {m.jump_url}"
                )

    except Exception:
        log.exception("/anonsend failed")
        await interaction.response.send_message(
            "That file's not an image, or is it?",
            ephemeral=True,
            file=File(ASSET_CONFUSED)
        )


@client.tree.command(name="help", description="How to use MechaHassaku, its commands, tools, and Ikena's citrus models")
async def help_command(interaction: Interaction) -> None:
    """Display help information (only the user who asked sees it)."""
    await interaction.response.send_message(
        embed=build_help_page("usage"), view=HelpView(), ephemeral=True
    )


# ==================== Help System ====================
HELP_COLOR = 0xf74e0d


def _help_base(title: str) -> Embed:
    embed = Embed(title=title, color=HELP_COLOR)
    if client.user and client.user.avatar:
        embed.set_thumbnail(url=client.user.avatar.url)
    return embed


def build_help_page(page: str) -> Embed:
    """Build one help page: "usage", "commands", "tools" or "about"."""
    if page == "tools":
        embed = _help_base("Tools & getting started")
        embed.add_field(
            name="🧰 Easiest way to start",
            value=(
                f"[Stability Matrix]({STABILITY_MATRIX_URL}) installs Forge Neo, ComfyUI and more in one click.\n"
                f"Follow the [installation guide]({STABILITY_MATRIX_INSTALL_URL})."
            ),
            inline=False
        )
        embed.add_field(
            name="🎨 Generate",
            value=(
                f"[Forge Neo]({FORGE_NEO_URL}) — simple web UI\n"
                f"[ComfyUI]({COMFYUI_URL}) — node-based, most flexible"
            ),
            inline=False
        )
        embed.add_field(
            name="🏷️ Train your own LoRA",
            value=(
                f"[VLCaptioner]({VLCAPTIONER_URL}) by Ikena — captions and Danbooru-style tags for datasets\n"
                f"[Kohya GUI]({KOHYA_URL}) — training"
            ),
            inline=False
        )
        embed.add_field(
            name="📦 Models",
            value="[Civitai](https://civitai.com) · [Hugging Face](https://huggingface.co)",
            inline=False
        )
        return embed

    if page == "commands":
        embed = _help_base("Commands")
        embed.add_field(
            name="/checkparameters",
            value=(
                "`image:` — check an image you upload\n"
                "`link:` — check an image that's already posted "
                "(right-click the message → Copy Message Link)\n"
                "Add `private: True` so only you see the result."
            ),
            inline=False
        )
        embed.add_field(
            name="/anonsend",
            value="`file:` — post an image without showing your name. Moderators can still see who sent it.",
            inline=False
        )
        embed.add_field(name="/help", value="This guide.", inline=False)
        embed.add_field(name="/ping", value="Check that I'm awake.", inline=False)
        return embed

    if page == "about":
        embed = _help_base("About citrus models")
        embed.description = (
            "AI Art & Models Hub is the home of Ikena's citrus models — "
            "every model is named after a Japanese citrus fruit 🍋.\n"
            "These days most images here are made with Anima or Illustrious models."
        )
        embed.add_field(
            name="Around the server",
            value=(
                f"📜 Rules: <#{RULES_CHANNEL_ID}>\n"
                f"🌈 Color roles: <#{COLOR_ROLES_CHANNEL_ID}>\n"
                f"🔗 Helpful links: <#{HELPFUL_LINKS_CHANNEL_ID}>"
            ),
            inline=False
        )
        embed.add_field(
            name="Support the models",
            value="Use the Civitai, SubscribeStar and SeaArt buttons below.",
            inline=False
        )
        return embed

    embed = _help_base("MechaHassaku — prompt checker")
    embed.description = "I read the prompt and settings saved inside AI-generated images and show them here."
    embed.add_field(
        name="📥 Check an image",
        value=(
            f"1. Post it in <#{AUTO_SHARE_CHANNEL_ID}> — I reply automatically.\n"
            "2. Use `/checkparameters` and attach the image (or paste a message link).\n"
            "3. Reply \"what model?\" to someone's image and I'll tell you the model."
        ),
        inline=False
    )
    embed.add_field(
        name="✅ Works with",
        value="Forge / A1111, ComfyUI, SwarmUI, NovelAI (V3–V5), and prompts hidden in the image pixels.",
        inline=False
    )
    embed.add_field(
        name="💡 Tip",
        value="Upload the original file. Screenshots and copy-pasted images lose the prompt.",
        inline=False
    )
    embed.add_field(name="❓ Questions?", value=f"Ask in <#{HELP_CHANNEL_ID}>", inline=False)
    return embed


class HelpView(discord.ui.View):
    """Page buttons for /help plus links to Ikena's pages."""

    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(discord.ui.Button(
            label="Civitai", style=discord.ButtonStyle.url, url=CIVITAI_URL, emoji="🎨", row=1
        ))
        self.add_item(discord.ui.Button(
            label="SubscribeStar", style=discord.ButtonStyle.url, url=SUBSCRIBESTAR_URL, emoji="🍋", row=1
        ))
        self.add_item(discord.ui.Button(
            label="SeaArt", style=discord.ButtonStyle.url, url=SEAART_URL, emoji="🌊", row=1
        ))

    async def _show(self, interaction: Interaction, page: str) -> None:
        await interaction.response.edit_message(embed=build_help_page(page), view=self)

    @discord.ui.button(label="How to use", emoji="📥", style=discord.ButtonStyle.blurple, row=0)
    async def usage_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "usage")

    @discord.ui.button(label="Commands", emoji="⌨️", style=discord.ButtonStyle.blurple, row=0)
    async def commands_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "commands")

    @discord.ui.button(label="Tools", emoji="🧰", style=discord.ButtonStyle.blurple, row=0)
    async def tools_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "tools")

    @discord.ui.button(label="About citrus models", emoji="🍋", style=discord.ButtonStyle.blurple, row=0)
    async def about_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "about")


if __name__ == "__main__":
    load_dotenv()
    # root_logger=True: also print our "mechahassaku" logs, not only discord.py's own
    client.run(os.environ["TOKEN"], root_logger=True)
