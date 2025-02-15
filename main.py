# -*- coding: utf-8 -*-
"""
Created on Sun Feb 25 20:42:17 2024

@author: seesthenight & Circle D5
"""

import os
import re
import pprint
import datetime
import discord
from discord.ext import commands
from discord.utils import get
from module.MechaHassakuException import MechaHassakuError
from PIL import Image
import time
import io
import math

from module.parser import parse_generation_parameters

# Configuration Parameter
auto_channel_name = '🤖│prompts-auto-share'
#####################

intents = discord.Intents.all()
intents.message_content = True
client = commands.Bot(command_prefix='$', intents=intents)


@client.event
async def on_ready():
    try:
        # Comment the following line to avoid getting ratelimited or potentially banned from Discord when restarting the bot very often for testing purposes
        # await client.tree.sync()
        print("Synced slash commands")
    except Exception as e:
        print("Error syncing slash cmds:", e)

    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Prerelease v0.9"))
    print("------------------------------------------------")
    print("Bot successfully deployed\nSession started at " + str(datetime.datetime.now()))
    print(f"Online as {client.user}")
    print("------------------------------------------------")


Limit_Length = 1000
# Insert a long string as an Embed field. (side effect)
def add_big_field(embed: discord.Embed, name: str, txt: str, inline=False):
    if len(txt) < Limit_Length:
        embed.add_field(name=name, value=txt, inline=inline)
    else:
        for i in range(math.ceil(len(txt) / Limit_Length)):
            text_value = txt[i * Limit_Length:(i + 1) * Limit_Length]
            embed.add_field(name=name + f"({i})", value=text_value, inline=inline)

async def analyzeAttachmentAndReply(attachment, response_destination, ephemeral=False):
    if not attachment.content_type.startswith("image"):
        return
    temp_file_name = None
    text_file_name = None
    try:
        downloaded_byte = await attachment.read()
        with io.BytesIO(downloaded_byte) as image_data:
            with Image.open(image_data) as image:
                temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                image.save(temp_file_name)
                data = image.info

                # パラメータが全く無い場合はメッセージを返信
                if not any(key in data for key in ["parameters", "prompt", "Comment"]):
                    await response_destination("No generation parameters found in this image.")
                    return

                # WebUIの場合：parametersキーが存在すればparse_generation_parameters()で解析
                if "parameters" in data:
                    ed = parse_generation_parameters(data["parameters"])
                else:
                    ed = {}

                # Novel AIの場合：data に "Comment" が存在すれば Novel AIと判断し各キーをマッピング
                if "Comment" in data:
                    ed["Prompt"] = data.get("prompt", "")
                    if "width" in data and "height" in data:
                        ed["Size-1"] = data["width"]
                        ed["Size-2"] = data["height"]
                    if "scale" in data:
                        ed["CFG scale"] = data["scale"]
                    if "seed" in data:
                        ed["Seed"] = data["seed"]
                    if "steps" in data:
                        ed["Steps"] = data["steps"]
                    if "sampler" in data:
                        ed["Sampler"] = data["sampler"]
                    if "uc" in data:
                        ed["Negative prompt"] = data["uc"]
                # ComfyUIの場合：Novel AIの"Comment"がないが"prompt"が存在する場合
                elif "prompt" in data:
                    ed["ComfyUI AI Params"] = data["prompt"]

                # 書き出し用にテキストファイルを生成
                text_file_name = f"./params_{int(time.time())}.txt"
                with open(text_file_name, "w", encoding="utf-8") as f:
                    pp = pprint.PrettyPrinter(stream=f, indent=4)
                    pp.pprint(data)

                # For debug
                print("\n\n", ed)

                embed, ifile = createPngInfoView(ed, temp_file_name)
                text_file = discord.File(text_file_name, filename="fullParameters.txt")

                if ephemeral:
                    await response_destination(embed=embed, file=ifile, ephemeral=ephemeral)
                    await response_destination(file=text_file, ephemeral=ephemeral)
                else:
                    await response_destination(embed=embed, file=ifile)
                    await response_destination(file=text_file)
    except Exception as err:
        print(err)
        eimageurl = "./assets/mecha_sorry.png"
        if isinstance(err, KeyError):
            message = ">>> > Sorry, but I couldn't retrieve parameters from the shared image; it seems the EXIF data is either missing or in an incorrect format."
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
        elif isinstance(err, AttributeError):
            message = ">>> > Sorry, the linked message is too old for me to access."
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
        else:
            message = ">>> > Some error due to my stupid masters' incompetence."
            print("Error details:", err)
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
    finally:
        # Cleanup temporary files
        if temp_file_name is not None and os.path.isfile(temp_file_name):
            os.remove(temp_file_name)
        if text_file_name is not None and os.path.isfile(text_file_name):
            os.remove(text_file_name)

async def analyzeAttachmentAndReply(attachment, response_destination, ephemeral=False):
    if not attachment.content_type.startswith("image"):
        return
    temp_file_name = None
    text_file_name = None
    try:
        downloaded_byte = await attachment.read()
        with io.BytesIO(downloaded_byte) as image_data:
            with Image.open(image_data) as image:
                temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                image.save(temp_file_name)

                data = image.info

                # No Parameters
                if not any(key in data for key in ["parameters", "prompt", "Comment"]):
                    await response_destination("No generation parameters found in this image.")
                    return

                # WebUI
                if "parameters" in data:
                    ed = parse_generation_parameters(data["parameters"])
                else:
                    ed = {}

                # ComfyUI 
                if "prompt" in data:
                    ed["ComfyUI AI Params"] = data["prompt"]
                # NovelAI
                if "Comment" in data:
                    ed["Novel AI Params"] = data["Comment"]

                # Write data to a text file
                text_file_name = f"./params_{int(time.time())}.txt"
                with open(text_file_name, "w", encoding="utf-8") as f:
                    pp = pprint.PrettyPrinter(stream=f, indent=4)
                    pp.pprint(data)

                # For debug
                print("\n\n", ed)

                embed, ifile = createPngInfoView(ed, temp_file_name)
                text_file = discord.File(text_file_name, filename="fullParameters.txt")

                if ephemeral:
                    await response_destination(embed=embed, file=ifile, ephemeral=ephemeral)
                    await response_destination(file=text_file, ephemeral=ephemeral)  # Send text file separately
                else:
                    await response_destination(embed=embed, file=ifile)
                    await response_destination(file=text_file)  # Send text file separately

    except Exception as err:
        print(err)
        eimageurl = "./assets/mecha_sorry.png"
        if isinstance(err, KeyError):
            message = ">>> > Sorry, but I couldn't retrieve parameters from the shared image; it seems the EXIF data is either missing or in an incorrect format."
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
        elif isinstance(err, AttributeError):
            message = ">>> > Sorry, the linked message is too old for me to access."
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
        else:
            message = ">>> > Some error due to my stupid masters' incompetence."
            print("Error details:", err)
            sorry_image = discord.File(eimageurl)
            raise MechaHassakuError(message, sorry_image) from None
    finally:
        # Cleanup temporary files
        if temp_file_name is not None and os.path.isfile(temp_file_name):
            os.remove(temp_file_name)
        if text_file_name is not None and os.path.isfile(text_file_name):
            os.remove(text_file_name)


async def analyzeAllAttachments(message):
    for attachment in message.attachments:
        # ignore not image attachments
        if not attachment.content_type.startswith("image"):
            continue
        # send a message saying "could see sent image"
        msg = await message.reply("analyzing....... <a:kururing:1113757022257696798> ", mention_author=False)
        try:
            await analyzeAttachmentAndReply(attachment, message.channel.send)
            await msg.delete()
        except MechaHassakuError as err:
            print(err)
            await msg.delete()
            await msg.channel.send(err.message, file=err.file)


async def modelRequestDetector(message):
    model_question_pattern = re.compile(
        r"(which\s+one|which\s+model|the\s+model|what\s+model|model\s+pls|model\s+please)",
        re.IGNORECASE
    )
    if model_question_pattern.search(message.content):
        print("triggered")  # debugging
        # Check if the message is a reply to another message
        if message.reference is not None:
            # Access the original message to which the user is replying and asking for which model they used
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            print("got reference message")  # debugging
            # Check for specific keywords in the content of the reply
            print("called handler function")  # debugging
            await modelRequestHandler(referenced_message, referenced_message.channel.send)
    else:
        print("no")  # debugging
        return


async def modelRequestHandler(message, response_destination):
    print("started handler function")  # debugging
    for attachment in message.attachments:
        # ignore not image attachments
        if attachment.content_type.startswith("image"):
            msg = await message.reply("Taking a look....... <a:kururing:1113757022257696798> ")
            temp_file_name = None
            try:
                downloaded_byte = await attachment.read()
                with io.BytesIO(downloaded_byte) as image_data:
                    with Image.open(image_data) as image:
                        temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                        image.save(temp_file_name)
                        print("saved image locally")  # debugging

                        data = image.info
                        ed = parse_generation_parameters(data["parameters"])
                        print("got metadata")
                        # For debug
                        print("\n\n", ed)

                        await response_destination(
                            f">>> The model used appears to be `{ed['Model']}` with the hash `{ed['Model hash']}` according to the image's metadata.\nTip: If you want all the gen parameters, run /checkparameters with a link to the message containing this image!")
                        await msg.delete()
            except Exception as err:
                await msg.delete()
                print("Model Request Handler error:", err)
            finally:
                if temp_file_name is not None and os.path.isfile(temp_file_name):
                    os.remove(temp_file_name)


@client.event
async def on_message(message):
    # ignore bot message
    if message.author == client.user:
        return
    await modelRequestDetector(message)
    # ignore event from another channel
    if str(message.channel) != auto_channel_name:
        return
    # ignore no attachments message
    if len(message.attachments) == 0:
        return

    start_time = time.time()
    print(message.attachments)
    await analyzeAllAttachments(message)
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Execution time: {elapsed_time} seconds")


@client.tree.command(name="ping", description="Check the latency of the bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f'>>> \U0001f3d3 Pong! Client Latency : `{round(client.latency * 1000)}ms`'
    )


@client.tree.command(
    name="checkparameters",
    description="Get Stable Diffusion generation settings and prompts used of an image from a linked message"
)
async def checkparameters(interaction: discord.Interaction, private_mode: bool, link: str):
    try:
        await interaction.response.defer(ephemeral=private_mode)
        start_time = time.time()
        # Split the link into parts
        parts = link.split('/')
        guild_id = int(parts[-3])
        channel_id = int(parts[-2])
        message_id = int(parts[-1])

        print("\nguild id:", guild_id, "\nchannel id:", channel_id, "\nmessage id:", message_id)

        # Get the message object from the link
        guild = client.get_guild(guild_id)
        channel = guild.get_channel(channel_id)
        message = await channel.fetch_message(message_id)

        print("\nnumber of attachments: ", len(message.attachments))
        if len(message.attachments) == 0:
            await interaction.followup.send("There's nothing attached, you know<:TeriDerp:1104059514501746689>?", ephemeral=private_mode)
            return

        for attachment in message.attachments:
            try:
                await analyzeAttachmentAndReply(attachment, interaction.followup.send, ephemeral=private_mode)
            except Exception as err:
                if isinstance(err, MechaHassakuError):
                    print(err)
                    await interaction.followup.send(err.message, file=err.file, ephemeral=private_mode)

            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"Execution time: {elapsed_time} seconds")
    except Exception as err:
        print(err)
        eimageurl = "./assets/mecha_sorry.png"
        await interaction.followup.send(">>> > Some error due to my stupid masters' incompetence.",
                                          file=discord.File(eimageurl), ephemeral=private_mode)


@client.tree.command(name="anonsend", description="Send images anonymously, if you're shy")
async def anonsend(interaction: discord.Interaction, file: discord.Attachment):
    try:
        # Get user_id for security
        user_id = interaction.user.id
        # Fetch channel to BotLogChannel
        channel = await client.fetch_channel(1120267966731259984)

        # Download the image to a temporary file
        download_byte = await file.read()
        with io.BytesIO(download_byte) as image_data:
            with Image.open(image_data) as image:
                image.save("aimage.png")
                await client.fetch_channel(interaction.channel_id)
                afile = discord.File("aimage.png")
                await interaction.response.send_message("Image sent anonymously!\n Only you can see this message :man_detective:", ephemeral=True)
                m = await interaction.followup.send(file=afile)
                # For security, output user id to BotLogChannel
                ml = m.jump_url
                await channel.send(f"User ID {user_id} sent an image anonymously! Jump to message: {ml}")
    except Exception as e:
        print(e)
        eimageurl = "./assets/confused.png"
        await interaction.response.send_message("That file's not an image, or is it?", ephemeral=True,
                                                  file=discord.File(eimageurl))
    finally:
        if os.path.isfile("aimage.png"):
            os.remove("aimage.png")


class helpbclass(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=300)
        self.value = None

        # create buttons with labels, styles, emojis and callbacks
        get_started_button = discord.ui.Button(
            label="Get Started", style=discord.ButtonStyle.blurple, emoji="🚀")
        utility_button = discord.ui.Button(label="Utility",
                                           style=discord.ButtonStyle.blurple,
                                           emoji="🔧")
        back_button = discord.ui.Button(label="Back",
                                        style=discord.ButtonStyle.red,
                                        emoji="◀️")
        patreon_button = discord.ui.Button(label="Ikena's Patreon",
                                           style=discord.ButtonStyle.url,
                                           url='https://www.patreon.com/user?u=27247323',
                                           emoji="🧡")

        # add the buttons to the view
        self.add_item(patreon_button)

    # TODO: update the following info to make it relevant and useful now
    @discord.ui.button(label="Get Started",
                         emoji="🚀",
                         style=discord.ButtonStyle.blurple)
    async def get_started_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed1 = discord.Embed(
            title="Requirements and Setting Up Stable Diffusion",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0x0062ff)
        embed1.set_author(name="Mecha Hassaku - Helpdesk",
                          icon_url=client.user.avatar.url)
        embed1.add_field(
            name=":one:  Requirements  :notepad_spiral:",
            value="Minimum Requirements:\n⊛ A > 4/6GB  VRAM GPU (Preferably Nvidia)\n⊛ Atleast 15GB of free disk space\n⊛ Windows 8, preferably 10/11",
            inline=False)
        embed1.add_field(
            name="Don't meet the requirements? Dont Worry!",
            value="You can use these (for free pretty much): https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Online-Services",
            inline=False)
        embed1.add_field(
            name=":two:  Installation  :gear:",
            value="Follow these:\n⊛ Windows: https://github.com/AUTOMATIC1111/stable-diffusion-webui#automatic-installation-on-windows\nVideo guide: https://www.youtube.com/watch?v=3cvP7yJotUM",
            inline=False)
        embed1.add_field(
            name="Too Lazy? Use this unofficial .exe installer for Windows",
            value="https://github.com/EmpireMediaScience/A1111-Web-UI-Installer",
            inline=False)
        embed1.add_field(
            name="Done. Now what?",
            value="By default the SD 1.5 model is installed but you can use many other models like Ikena's Hassaku from civitai.com. Save them to the `stable-diffusion-webui/models/Stable-diffusion` path in your computer",
            inline=False)

        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed1)

    @discord.ui.button(label="Utility",
                         emoji="🔧",
                         style=discord.ButtonStyle.blurple)
    async def utility_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed2 = discord.Embed(
            title="Utility Tools & Resources",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0x0062ff)
        embed2.set_author(name="Mecha Hassaku - Helpdesk",
                          icon_url=client.user.avatar.url)
        embed2.add_field(name=":two: Helpful Stuff :toolbox:",
                         value="Links to helpful resources and tools ",
                         inline=False)
        embed2.add_field(
            name="StableDiffusion Wiki",
            value="https://www.reddit.com/r/StableDiffusion/wiki/index/",
            inline=False)
        embed2.add_field(
            name="Download Models, LoRAs, VAEs and More",
            value="CivitAI: https://civitai.com\nHuggingFace:https://huggingface.co ",
            inline=False)
        embed2.add_field(
            name="Training tools",
            value="Kohya GUI: https://github.com/bmaltais/kohya_ss\nImage/Dataset Captioning tool: https://github.com/toriato/stable-diffusion-webui-wd14-tagger ",
            inline=False)

        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed2)

    @discord.ui.button(label="Back",
                         emoji="◀️",
                         style=discord.ButtonStyle.danger)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="MechaHassaku Helpdesk",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0xf74e0d)
        embed.add_field(
            name=":one:  Beginners Guide to Stable Diffusion :rocket:",
            value="Guides to go from setting up till image generation ",
            inline=False)
        embed.add_field(
            name=":two:  Utility - Helpful Resources :wrench:",
            value="Compilation of helpful tools, resources, models etc.",
            inline=False)
        embed.add_field(
            name="See an image you like and want to generate similar images?",
            value="Use my flagship feature to find out the prompt and generation settings used from an SD AI generated image! Just type `/imageparameters` in the chat box and you will be prompted to upload the image.",
            inline=False)
        embed.add_field(
            name="Check out Ikena's Stable Diffusion models for all your needs: Anime, Hentai & Semi-Realistic",
            value="https://civitai.com/user/Ikena/models \nIf you like his work, consider donating on Patreon\n**Still have questions? Ask away at <#1072336225496739970>**",
            inline=False)
        embed.set_footer(
            text="This is an early version of the bot. If you find something wrong or have suggestions, feel free to contact me (manofculture#0644)"
        )
        embed.set_thumbnail(url=client.user.avatar.url)
        view = helpbclass()

        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed, view=view)


@client.tree.command(
    name="help",
    description="Help on how to use the bot and Stable Diffusion guides")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="MechaHassaku Helpdesk",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
        color=0xf74e0d)
    embed.set_thumbnail(url=client.user.avatar.url)
    embed.add_field(
        name=":one:  Beginners Guide to Stable Diffusion :rocket:",
        value="Guides to go from setting up till image generation ",
        inline=False)
    embed.add_field(
        name=":two:  Utility - Helpful Resources :wrench:",
        value="Compilation of helpful tools, resources, models etc.",
        inline=False)
    embed.add_field(
        name="See an image you like and want to generate similar images?",
        value="Use my flagship feature to find out the prompt and generation settings used from an SD AI generated image! Just type `/imageparameters` in the text box and you will be prompted to upload the image.",
        inline=False)
    embed.add_field(
        name="Check out Ikena's Stable Diffusion models for all your needs: Anime, Hentai & Semi-Realistic",
        value="https://civitai.com/user/Ikena/models \nIf you like his work, consider donating on Patreon\n**Still have questions? Ask away at <#1072336225496739970>**",
        inline=False)
    embed.set_footer(
        text="This is an early version of the bot. If you find something wrong or have suggestions, feel free to contact me (manofculture#0644)"
    )
    view = helpbclass()
    await interaction.response.send_message(embed=embed, view=view)


clienttoken = os.environ["TOKEN"]
client.run(clienttoken)
