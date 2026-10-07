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
import datetime
from typing import Optional, Tuple, Dict, Any, Callable
from dotenv import load_dotenv

import discord
from discord.ext import commands
from discord import File, Embed, Interaction, Attachment, app_commands
from dotenv import load_dotenv
from PIL import Image

from module.MechaHassakuException import MechaHassakuError
from module.parser import parse_generation_parameters, parse_novelai_parameters
from module.metadata import has_parameters, read_image_metadata


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

# File paths
ASSET_SORRY = "./assets/mecha_sorry.png"
ASSET_CONFUSED = "./assets/mecha_confused.png"


class MechaHassakuBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Register slash commands with Discord. Runs once per process start, i.e. on each deploy.
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"Error syncing slash commands: {e}")


# Bot setup
intents = discord.Intents.all()
intents.message_content = True
client = MechaHassakuBot(command_prefix='$', intents=intents)


# ==================== Bot Events ====================
@client.event
async def on_ready() -> None:
    """Initialize bot on startup."""
    await client.change_presence(activity=discord.CustomActivity(name=BOT_STATUS))

    print("------------------------------------------------")
    print(f"Bot successfully deployed\nSession started at {datetime.datetime.now()}")
    print(f"Online as {client.user}")
    print("------------------------------------------------")


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
    print(message.attachments)
    await analyze_all_attachments(message)
    elapsed_time = time.time() - start_time
    print(f"Execution time: {elapsed_time:.2f} seconds")


# ==================== Embed Creation ====================
def add_big_field(embed: Embed, name: str, txt: str, inline: bool = False) -> None:
    """Add a field to embed, splitting into multiple fields if text exceeds limit."""
    if len(txt) < EMBED_FIELD_LIMIT:
        embed.add_field(name=name, value=txt, inline=inline)
    else:
        chunks = math.ceil(len(txt) / EMBED_FIELD_LIMIT)
        for i in range(chunks):
            start = i * EMBED_FIELD_LIMIT
            end = (i + 1) * EMBED_FIELD_LIMIT
            text_value = txt[start:end]
            embed.add_field(name=f"{name}({i})", value=text_value, inline=inline)


def create_pnginfo_view(pnginfo_kv: Dict[str, Any], icon_path: str) -> tuple[Embed, File]:
    """Create an embed displaying PNG generation parameters."""
    tags = _detect_tags(pnginfo_kv)
    title_tags = "   ".join(f"` {tag} `" for tag in tags) if tags else "FAILED TO GET TAGS"
    
    embed = Embed(
        title=f"Image Prompt & Settings :tools:\n{title_tags}",
        color=0x7101fa
    )
    
    # Only add embed fields if not ComfyUI
    if pnginfo_kv.get("ui_type") != "comfyui":
        _add_prompt_fields(embed, pnginfo_kv)
        _add_generation_fields(embed, pnginfo_kv)
        _add_hires_fields(embed, pnginfo_kv)
        _add_model_fields(embed, pnginfo_kv)
    else:
        # For ComfyUI, just set the description
        embed.description = "ComfyUI workflow detected. Full metadata attached below :arrow_double_down:"
    
    # Remove metadata keys not needed in embed
    for key in ['ComfyUI AI Params', 'Novel AI Params', 'Generation date', 'Generation time', 'SwarmUI version', 'Aspect ratio']:
        pnginfo_kv.pop(key, None)
    
    ifile = File(icon_path)
    url = "attachment://" + icon_path[2:]
    embed.set_thumbnail(url=url)
    
    return embed, ifile


def _detect_tags(pnginfo_kv: Dict[str, Any]) -> list[str]:
    """Detect and return tags based on image metadata."""
    tags = []
    print("DEBUG")
    print(pnginfo_kv)
    
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
    model = pnginfo_kv.get('Model', '').lower()
    if model:
        if any(keyword in model for keyword in ['illustrious', 'noob', 'wai']):
            tags.append('ILLUSTRIOUS')
        elif 'xl' in model or 'sdxl' in model:
            tags.append('SDXL')
        elif 'pony' in model:
            tags.append('PONY')
        elif 'flux' in model:
            tags.append('FLUX')
    
    # Detect LoRA type
    prompt = pnginfo_kv.get('Prompt', '').lower()
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



def _add_prompt_fields(embed: Embed, kv: Dict[str, Any]) -> None:
    """Add prompt-related fields to embed."""
    if 'Prompt' in kv:
        add_big_field(embed, '__Prompt__ :keyboard:', kv['Prompt'], False)
    if 'Negative prompt' in kv:
        add_big_field(embed, '__Negative Prompt__ :no_entry_sign:', kv['Negative prompt'], False)


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
        if key in kv:
            embed.add_field(name=name, value=kv[key], inline=inline)
    # Add scheduler if present (SwarmUI/ComfyUI)
    if 'Schedule type' in kv and kv['Schedule type'] != 'Automatic':
        embed.add_field(name='__Scheduler__ :calendar:', value=kv['Schedule type'], inline=True)
    # Image size (special handling)
    if 'Size-1' in kv and 'Size-2' in kv:
        size = f"{kv['Size-1']}x{kv['Size-2']}"
        embed.add_field(name='__Image Size__ :straight_ruler:', value=size, inline=True)


def _add_hires_fields(embed: Embed, kv: Dict[str, Any]) -> None:
    """Add hires fix fields to embed."""
    if 'Hires upscaler' not in kv:
        return
    
    embed.add_field(name='__Hires. Upscaler__ :arrow_double_up:', value=kv['Hires upscaler'], inline=True)
    
    if 'Hires upscale' in kv:
        embed.add_field(name='__Hires. Upscale__ :eight_spoked_asterisk:', value=kv['Hires upscale'], inline=True)
    
    if 'Denoising strength' in kv:
        embed.add_field(name='__Denoising Strength__ :muscle:', value=kv['Denoising strength'], inline=True)


def _add_model_fields(embed: Embed, kv: Dict[str, Any]) -> None:
    """Add model-related fields to embed."""
    model = kv.get('Model')
    if model:
        is_xl = any(tag in model.upper() for tag in ['XL', 'SDXL'])
        name = '__Model__ :regional_indicator_x::regional_indicator_l:' if is_xl else '__Model__ :art:'
        embed.add_field(name=name, value=model, inline=True)
    
    if 'Model hash' in kv:
        embed.add_field(name='__Model Hash__ :key:', value=kv['Model hash'], inline=True)
    
    # Add VAE if present
    if 'VAE' in kv:
        embed.add_field(name='__VAE__ :file_folder:', value=kv['VAE'], inline=True)
    
    # Add LoRAs if present (ComfyUI specific)
    if 'LoRAs' in kv:
        add_big_field(embed, '__LoRAs__ :jigsaw:', kv['LoRAs'], inline=False)
    


# ==================== Image Analysis ====================
async def analyze_attachment_and_reply(
    attachment: Attachment,
    response_destination: Callable,
    ephemeral: bool = False
) -> None:
    """Analyze a single image attachment and reply with parameters."""
    if not attachment.content_type.startswith("image"):
        return
    
    temp_file_name = None
    text_file_name = None
    
    try:
        downloaded_byte = await attachment.read()
        
        with io.BytesIO(downloaded_byte) as image_data:
            with Image.open(image_data) as image:
                # Save temporary file
                temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                image.save(temp_file_name)
                
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
                
                # Create text file with full parameters
                text_file_name = f"./params_{int(time.time())}.txt"
                with open(text_file_name, "w", encoding="utf-8") as f:
                    pp = pprint.PrettyPrinter(stream=f, indent=4)
                    pp.pprint(data)
                
                # Debug output
                print("\n\n", ed)
                
                # Create and send embed
                embed, ifile = create_pnginfo_view(ed, temp_file_name)
                text_file = File(text_file_name, filename="fullParameters.txt")
                
                if ephemeral:
                    await response_destination(embed=embed, file=ifile, ephemeral=ephemeral)
                    await response_destination(file=text_file, ephemeral=ephemeral)
                else:
                    await response_destination(embed=embed, file=ifile)
                    await response_destination(file=text_file)
                    
    except Exception as err:
        print(err)
        _handle_analysis_error(err, response_destination)
        
    finally:
        # Cleanup temporary files
        for filename in [temp_file_name, text_file_name]:
            if filename and os.path.isfile(filename):
                os.remove(filename)


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
    print("Error details:", err)
    
    sorry_image = File(ASSET_SORRY)
    raise MechaHassakuError(message, sorry_image) from None


async def analyze_all_attachments(message: discord.Message) -> None:
    """Analyze all image attachments in a message."""
    for attachment in message.attachments:
        if not attachment.content_type.startswith("image"):
            continue
        
        msg = await message.reply("Analyzing image >>> <a:kururing:1113757022257696798> ", mention_author=False)
        
        try:
            await analyze_attachment_and_reply(attachment, message.channel.send)
            await msg.delete()
        except MechaHassakuError as err:
            print(err)
            await msg.delete()
            await msg.channel.send(err.message, file=err.file)


# ==================== Model Request Detection ====================
async def model_request_detector(message: discord.Message) -> None:
    """Detect if a message is asking about a model and respond."""
    pattern = re.compile(
        r"(which\s+one|which\s+model|the\s+model|what\s+model|model\s+pls|model\s+please)",
        re.IGNORECASE
    )
    
    if not pattern.search(message.content):
        print("no")
        return
    
    print("triggered")
    
    if message.reference is None:
        return
    
    try:
        referenced_message = await message.channel.fetch_message(message.reference.message_id)
        print("got reference message")
        await model_request_handler(referenced_message, referenced_message.channel.send)
    except Exception as e:
        print(f"Error in model request detector: {e}")


async def model_request_handler(message: discord.Message, response_destination: Callable) -> None:
    """Handle model information request for a message."""
    print("started handler function")
    
    for attachment in message.attachments:
        if not attachment.content_type.startswith("image"):
            continue
        
        msg = await message.reply("Taking a look....... <a:kururing:1113757022257696798> ")
        temp_file_name = None
        
        try:
            downloaded_byte = await attachment.read()
            
            with io.BytesIO(downloaded_byte) as image_data:
                with Image.open(image_data) as image:
                    temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                    image.save(temp_file_name)
                    print("saved image locally")
                    
                    data = image.info
                    ed = parse_generation_parameters(data["parameters"])
                    print("got metadata")
                    print("\n\n", ed)
                    
                    response_text = (
                        f">>> The model used appears to be `{ed['Model']}` with the hash "
                        f"`{ed['Model hash']}` according to the image's metadata.\n"
                        f"Tip: If you want all the gen parameters, run /checkparameters with "
                        f"a link to the message containing this image!"
                    )
                    await response_destination(response_text)
                    await msg.delete()
                    
        except Exception as err:
            await msg.delete()
            print("Model Request Handler error:", err)
            
        finally:
            if temp_file_name and os.path.isfile(temp_file_name):
                os.remove(temp_file_name)


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
                print(err)
                await interaction.followup.send(err.message, file=err.file, ephemeral=private)

        elapsed_time = time.time() - start_time
        print(f"Execution time: {elapsed_time:.2f} seconds")

    except Exception as err:
        print(err)
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
    """Send an image anonymously."""
    temp_file = "aimage.png"

    try:
        user_id = interaction.user.id
        channel = await client.fetch_channel(BOT_LOG_CHANNEL_ID)

        # Download and save image
        download_byte = await file.read()
        with io.BytesIO(download_byte) as image_data:
            with Image.open(image_data) as image:
                image.save(temp_file)

                await client.fetch_channel(interaction.channel_id)
                afile = File(temp_file)

                await interaction.response.send_message(
                    "Image sent anonymously!\n Only you can see this message :man_detective:",
                    ephemeral=True
                )

                m = await interaction.followup.send(file=afile)

                # Log for security
                await channel.send(
                    f"User ID {user_id} sent an image anonymously! Jump to message: {m.jump_url}"
                )

    except Exception as e:
        print(e)
        await interaction.response.send_message(
            "That file's not an image, or is it?",
            ephemeral=True,
            file=File(ASSET_CONFUSED)
        )

    finally:
        if os.path.isfile(temp_file):
            os.remove(temp_file)


@client.tree.command(name="help", description="How to use MechaHassaku, its commands, and Ikena's citrus models")
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
    """Build one help page: "usage", "commands" or "about"."""
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
            value="Use the Civitai and SubscribeStar buttons below.",
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
        self.add_item(discord.ui.Button(label="Civitai", style=discord.ButtonStyle.url, url=CIVITAI_URL, emoji="🎨"))
        self.add_item(discord.ui.Button(
            label="SubscribeStar", style=discord.ButtonStyle.url, url=SUBSCRIBESTAR_URL, emoji="🍋"
        ))

    async def _show(self, interaction: Interaction, page: str) -> None:
        await interaction.response.edit_message(embed=build_help_page(page), view=self)

    @discord.ui.button(label="How to use", emoji="📥", style=discord.ButtonStyle.blurple, row=0)
    async def usage_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "usage")

    @discord.ui.button(label="Commands", emoji="⌨️", style=discord.ButtonStyle.blurple, row=0)
    async def commands_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "commands")

    @discord.ui.button(label="About citrus models", emoji="🍋", style=discord.ButtonStyle.blurple, row=0)
    async def about_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "about")


if __name__ == "__main__":
    load_dotenv()
    client.run(os.environ["TOKEN"])
