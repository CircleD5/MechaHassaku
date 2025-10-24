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

import discord
from discord.ext import commands
from discord import File, Embed, Interaction, Attachment
from dotenv import load_dotenv
from PIL import Image

from module.MechaHassakuException import MechaHassakuError
from module.parser import parse_generation_parameters


# ==================== Configuration ====================
AUTO_CHANNEL_NAME = '🤖│prompts-auto-share'
EMBED_FIELD_LIMIT = 1000
BOT_LOG_CHANNEL_ID = 1120267966731259984

# File paths
ASSET_SORRY = "./assets/mecha_sorry.png"
ASSET_CONFUSED = "./assets/confused.png"

# Bot setup
intents = discord.Intents.all()
intents.message_content = True
client = commands.Bot(command_prefix='$', intents=intents)


# ==================== Bot Events ====================
@client.event
async def on_ready() -> None:
    """Initialize bot on startup."""
    try:
        # Uncomment to sync slash commands (avoid rate limiting during testing)
        # await client.tree.sync()
        print("Synced slash commands")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")

    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Prerelease v0.9"
        )
    )
    
    print("------------------------------------------------")
    print(f"Bot successfully deployed\nSession started at {datetime.datetime.now()}")
    print(f"Online as {client.user}")
    print("------------------------------------------------")


@client.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages."""
    if message.author == client.user:
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
                
                data = image.info
                
                # Check if parameters exist
                if not any(key in data for key in ["parameters", "prompt", "Comment"]):
                    await response_destination("No parameters detected. Upload the image instead of pasting it.")
                    return
                
                # Parse parameters based on UI type
                ed = _parse_parameters(data)
                
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
        ed.update({
            "Prompt": data.get("prompt", ""),
            "Negative prompt": data.get("uc", ""),
            "CFG scale": data.get("scale"),
            "Seed": data.get("seed"),
            "Steps": data.get("steps"),
            "Sampler": data.get("sampler"),
        })
        if "width" in data and "height" in data:
            ed["Size-1"] = data["width"]
            ed["Size-2"] = data["height"]
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
@client.tree.command(name="ping", description="Check the latency of the bot")
async def ping(interaction: Interaction) -> None:
    """Respond with bot latency."""
    latency_ms = round(client.latency * 1000)
    await interaction.response.send_message(
        f'>>> \U0001f3d3 Pong! Client Latency : `{latency_ms}ms`'
    )


@client.tree.command(
    name="checkparameters",
    description="Get Stable Diffusion generation settings and prompts used of an image from a linked message"
)
async def checkparameters(interaction: Interaction, private_mode: bool, link: str) -> None:
    """Check parameters from a linked message."""
    try:
        await interaction.response.defer(ephemeral=private_mode)
        start_time = time.time()
        
        # Parse message link
        parts = link.split('/')
        guild_id = int(parts[-3])
        channel_id = int(parts[-2])
        message_id = int(parts[-1])
        
        print(f"\nguild id: {guild_id}\nchannel id: {channel_id}\nmessage id: {message_id}")
        
        # Fetch message
        guild = client.get_guild(guild_id)
        channel = guild.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        
        print(f"\nnumber of attachments: {len(message.attachments)}")
        
        if not message.attachments:
            await interaction.followup.send(
                "There's nothing attached, you know<:TeriDerp:1104059514501746689>?",
                ephemeral=private_mode
            )
            return
        
        # Process all attachments
        for attachment in message.attachments:
            try:
                await analyze_attachment_and_reply(
                    attachment,
                    interaction.followup.send,
                    ephemeral=private_mode
                )
            except MechaHassakuError as err:
                print(err)
                await interaction.followup.send(err.message, file=err.file, ephemeral=private_mode)
        
        elapsed_time = time.time() - start_time
        print(f"Execution time: {elapsed_time:.2f} seconds")
        
    except Exception as err:
        print(err)
        await interaction.followup.send(
            ">>> > Some error due to my stupid masters' incompetence.",
            file=File(ASSET_SORRY),
            ephemeral=private_mode
        )


@client.tree.command(name="anonsend", description="Send images anonymously, if you're shy")
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


@client.tree.command(
    name="help",
    description="Help on how to use the bot and Stable Diffusion guides"
)
async def help_command(interaction: Interaction) -> None:
    """Display help information."""
    embed = _create_help_embed()
    view = HelpButtonView()
    await interaction.response.send_message(embed=embed, view=view)


# ==================== Help System ====================
def _create_help_embed() -> Embed:
    """Create the main help embed."""
    embed = Embed(
        title="MechaHassaku Helpdesk",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
        color=0xf74e0d
    )
    embed.set_thumbnail(url=client.user.avatar.url)
    
    embed.add_field(
        name=":one:  Beginners Guide to Stable Diffusion :rocket:",
        value="Guides to go from setting up till image generation ",
        inline=False
    )
    embed.add_field(
        name=":two:  Utility - Helpful Resources :wrench:",
        value="Compilation of helpful tools, resources, models etc.",
        inline=False
    )
    embed.add_field(
        name="See an image you like and want to generate similar images?",
        value=(
            "Use my flagship feature to find out the prompt and generation settings used from "
            "an SD AI generated image! Just type `/imageparameters` in the text box and you will "
            "be prompted to upload the image."
        ),
        inline=False
    )
    embed.add_field(
        name="Check out Ikena's Stable Diffusion models for all your needs: Anime, Hentai & Semi-Realistic",
        value=(
            "https://civitai.com/user/Ikena/models \n"
            "If you like his work, consider donating on Patreon\n"
            "**Still have questions? Ask away at <#1072336225496739970>**"
        ),
        inline=False
    )
    embed.set_footer(
        text=(
            "This is an early version of the bot. If you find something wrong or have "
            "suggestions, feel free to contact me (manofculture#0644)"
        )
    )
    
    return embed


class HelpButtonView(discord.ui.View):
    """View containing help navigation buttons."""
    
    def __init__(self):
        super().__init__(timeout=300)
        
        # Add Patreon button
        patreon_button = discord.ui.Button(
            label="Ikena's Patreon",
            style=discord.ButtonStyle.url,
            url='https://www.patreon.com/user?u=27247323',
            emoji="🧡"
        )
        self.add_item(patreon_button)
    
    @discord.ui.button(label="Get Started", emoji="🚀", style=discord.ButtonStyle.blurple)
    async def get_started_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        """Show getting started guide."""
        embed = Embed(
            title="Requirements and Setting Up Stable Diffusion",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0x0062ff
        )
        embed.set_author(name="Mecha Hassaku - Helpdesk", icon_url=client.user.avatar.url)
        
        embed.add_field(
            name=":one:  Requirements  :notepad_spiral:",
            value=(
                "Minimum Requirements:\n"
                "⊛ A > 4/6GB  VRAM GPU (Preferably Nvidia)\n"
                "⊛ Atleast 15GB of free disk space\n"
                "⊛ Windows 8, preferably 10/11"
            ),
            inline=False
        )
        embed.add_field(
            name="Don't meet the requirements? Dont Worry!",
            value="You can use these (for free pretty much): https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Online-Services",
            inline=False
        )
        embed.add_field(
            name=":two:  Installation  :gear:",
            value=(
                "Follow these:\n"
                "⊛ Windows: https://github.com/AUTOMATIC1111/stable-diffusion-webui#automatic-installation-on-windows\n"
                "Video guide: https://www.youtube.com/watch?v=3cvP7yJotUM"
            ),
            inline=False
        )
        embed.add_field(
            name="Too Lazy? Use this unofficial .exe installer for Windows",
            value="https://github.com/EmpireMediaScience/A1111-Web-UI-Installer",
            inline=False
        )
        embed.add_field(
            name="Done. Now what?",
            value=(
                "By default the SD 1.5 model is installed but you can use many other models like "
                "Ikena's Hassaku from civitai.com. Save them to the "
                "`stable-diffusion-webui/models/Stable-diffusion` path in your computer"
            ),
            inline=False
        )
        
        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed)
    
    @discord.ui.button(label="Utility", emoji="🔧", style=discord.ButtonStyle.blurple)
    async def utility_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        """Show utility resources."""
        embed = Embed(
            title="Utility Tools & Resources",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0x0062ff
        )
        embed.set_author(name="Mecha Hassaku - Helpdesk", icon_url=client.user.avatar.url)
        
        embed.add_field(
            name=":two: Helpful Stuff :toolbox:",
            value="Links to helpful resources and tools ",
            inline=False
        )
        embed.add_field(
            name="StableDiffusion Wiki",
            value="https://www.reddit.com/r/StableDiffusion/wiki/index/",
            inline=False
        )
        embed.add_field(
            name="Download Models, LoRAs, VAEs and More",
            value="CivitAI: https://civitai.com\nHuggingFace:https://huggingface.co ",
            inline=False
        )
        embed.add_field(
            name="Training tools",
            value=(
                "Kohya GUI: https://github.com/bmaltais/kohya_ss\n"
                "Image/Dataset Captioning tool: https://github.com/toriato/stable-diffusion-webui-wd14-tagger "
            ),
            inline=False
        )
        
        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed)
    
    @discord.ui.button(label="Back", emoji="◀️", style=discord.ButtonStyle.danger)
    async def back_button(self, interaction: Interaction, button: discord.ui.Button) -> None:
        """Return to main help menu."""
        embed = _create_help_embed()
        view = HelpButtonView()
        
        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed, view=view)


clienttoken = os.environ["TOKEN"]
client.run(clienttoken)