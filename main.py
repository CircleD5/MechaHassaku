# -*- coding: utf-8 -*-
"""
Created on Sun Feb 25 20:42:17 2024

@author: seesthenight & Circle D5
"""

import os
import re
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
client = commands.Bot(command_prefix='$',
                      intents=intents)


@client.event
async def on_ready():
    try:
        #Comment the following line to avoid getting ratelimited or potentially banned from Discord when restarting the bot very often for testing purposes
        #await client.tree.sync()
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
# Insert a long string as an Embed field.(side effect)
def add_big_field(embed:discord.Embed, name:str, txt:str,  inline = False):
    if len(txt) < Limit_Length:
        embed.add_field(name=name, value=txt, inline=inline)
    else:
        for i in range(math.ceil(len(txt)/Limit_Length)):
            text_value = txt[i*Limit_Length:(i+1)*Limit_Length]
            embed.add_field(name=name + f"({i})", value=text_value, inline=inline)




#Populate generation info in an embed
def createPngInfoView(pnginfoKV, icon_path):
    embed = discord.Embed(title="Image Prompt & Settings :tools:", color=0x7101fa)
    
    # Automatic1111 用のパラメータ（存在する場合のみ表示）
    if 'Prompt' in pnginfoKV:
        add_big_field(embed, '__Prompt__ :keyboard:', pnginfoKV['Prompt'], False)
    if 'Negative prompt' in pnginfoKV:
        add_big_field(embed, '__Negative Prompt__ :no_entry_sign:', pnginfoKV['Negative prompt'], False)
    if 'Seed' in pnginfoKV:
        embed.add_field(name='__Seed__ :game_die:', value=pnginfoKV['Seed'], inline=True)
    if 'Sampler' in pnginfoKV:
        embed.add_field(name='__Sampler__ :cyclone:', value=pnginfoKV['Sampler'], inline=True)
    if 'CFG scale' in pnginfoKV:
        embed.add_field(name='__CFG Scale__ :level_slider:', value=pnginfoKV['CFG scale'], inline=True)
    if 'Size-1' in pnginfoKV and 'Size-2' in pnginfoKV:
        embed.add_field(name='__Image Size__ :straight_ruler:', value=pnginfoKV['Size-1']+"x"+pnginfoKV["Size-2"], inline=True)
    if 'Steps' in pnginfoKV:
        embed.add_field(name='__Steps__ :person_walking:', value=pnginfoKV['Steps'], inline=True)
    if 'Clip skip' in pnginfoKV:
        embed.add_field(name='__Clip Skip__ :paperclip:', value=pnginfoKV['Clip skip'], inline=True)

    if 'Hires upscaler' in pnginfoKV:
        embed.add_field(name='__Hires. Fix__ :mag_right:', value='On  ✅', inline=True)
        embed.add_field(name='__Hires. Upscaler__ :arrow_double_up:', value=pnginfoKV['Hires upscaler'], inline=True)

        if 'Hires upscale' in pnginfoKV:
            embed.add_field(name='__Hires. Upscale__ :eight_spoked_asterisk:', value=pnginfoKV['Hires upscale'], inline=True)
        if 'Denoising strength' in pnginfoKV:
            embed.add_field(name='__Denoising Strength__ :muscle:', value=pnginfoKV['Denoising strength'], inline=True)
    else:
        embed.add_field(name='__Hires. Fix__ :mag_right:', value='Off  ❌', inline=True)
    if 'Model' in pnginfoKV:
        if 'XL' in pnginfoKV['Model'] or 'SDXL' in pnginfoKV['Model']:
            embed.add_field(name='__Model__ :regional_indicator_x::regional_indicator_l:', value=pnginfoKV['Model'], inline=True)
        else:
            embed.add_field(name='__Model__ :art:', value=pnginfoKV['Model'], inline=True)
    if 'Model hash' in pnginfoKV:
        embed.add_field(name='__Model Hash__ :key:', value=pnginfoKV['Model hash'], inline=True)
    
    # ★ 新機能 ★
    # ComfyUI 対応：'prompt' キーから追加した情報を専用フィールドとして表示
    if 'ComfyUI AI Params' in pnginfoKV:
        add_big_field(embed, 'ComfyUI AI Params :gear:', pnginfoKV['ComfyUI AI Params'], False)
        del pnginfoKV['ComfyUI AI Params']
    # NovelAI 対応：'Comment' キーから追加した情報を専用フィールドとして表示
    if 'Novel AI Params' in pnginfoKV:
        add_big_field(embed, 'Novel AI Params :gear:', pnginfoKV['Novel AI Params'], False)
        del pnginfoKV['Novel AI Params']
    
    # その他のパラメータ（自動生成されたパラメータ以外）
    delkeys = ['Prompt', 'Negative prompt', 'Steps', 'Seed', 'Sampler', 'CFG scale', 'Size-1', 'Size-2', 
               'Clip skip', 'Model', 'Model hash', 'Hires upscaler', 'Hires upscale', 'Denoising strength']
    other_parameters = ', '.join(f'__{key}__: {value}' for key, value in pnginfoKV.items() if key not in delkeys)
    if other_parameters:
        add_big_field(embed, 'Other Params :gear:', other_parameters, False)
    
    ifile = discord.File(icon_path)
    url = "attachment://" + icon_path[2:]
    print(url)
    embed.set_thumbnail(url=url)
    return embed, ifile


async def analyzeAttachmentAndReply(attachment, response_destination, ephemeral=False):
    if not attachment.content_type.startswith("image"):
        return
    try:
        downloaded_byte = await attachment.read()
        temp_file_name = ""
        with io.BytesIO(downloaded_byte) as image_data:
            with Image.open(image_data) as image:
                temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                image.save(temp_file_name)
                
                data = image.info
                #  WEBUI
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
                
                # For debug
                print("\n\n", ed)
                
                embed, ifile = createPngInfoView(ed, temp_file_name)
                if ephemeral:
                    await response_destination(embed=embed, file=ifile, ephemeral=ephemeral)
                else:
                    await response_destination(embed=embed, file=ifile)
    except Exception as err:
        print(err)
        eimageurl = "./assets/mecha_sorry.png"
        message = ""
        if isinstance(err, KeyError):
            message = ">>> > Sorry, but I couldn't retrieve parameters from the shared image; it seems the EXIF data is either missing or in an incorrect format."
            sorry_image = discord.File(eimageurl)
        elif isinstance(err, AttributeError):
            message = ">>> > Sorry, the linked message is too old for me to access."
            sorry_image = discord.File(eimageurl)
        else:
            message = ">>> > Some error due to my stupid masters' incompetence."
            sorry_image = discord.File(eimageurl)
        raise MechaHassakuError(message, sorry_image) from None
    finally:
        if temp_file_name is not None and os.path.isfile(temp_file_name):
            os.remove(temp_file_name)


async def analyzeAllAttachments(message):
    for attachment in message.attachments:
        # ignore not image attachments
        if not attachment.content_type.startswith("image"):
            continue
        # send a message saying "could see sent image"
        msg= await message.reply("analyzing....... <a:kururing:1113757022257696798> ", mention_author=False)  
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
        print("triggered") #debugging
        # Check if the message is a reply to another message
        if message.reference is not None:
            # Access the original message to which the user is replying and asking for which model they used
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            print("got reference message") #debugging
            # Check for specific keywords in the content of the reply
            print("called handler function") #debugging
            await modelRequestHandler(referenced_message, referenced_message.channel.send)
    else:
        print("no") #debugging
        return

async def modelRequestHandler(message, response_destination):
    print("started handler function") #debugging
    for attachment in message.attachments:
        # ignore not image attachments
        if attachment.content_type.startswith("image"):
            msg= await message.reply("Taking a look....... <a:kururing:1113757022257696798> ")  
            try:
                downloaded_byte = await attachment.read()
                temp_file_name = ""
                with io.BytesIO(downloaded_byte) as image_data:
                    with Image.open(image_data) as image:
                        temp_file_name = f"./t{int(round(time.time() * 1000))}.png"
                        image.save(temp_file_name)
                        print("saved image locally") #debugging
                        
                        data = image.info
                        ed = parse_generation_parameters(data["parameters"])
                        print("got metadata")
                        #For debug
                        print("\n\n",ed)
                        
                        await response_destination(f">>> The model used appears to be `{ed['Model']}` with the hash `{ed['Model hash']}` according to the image's metadata.\nTip: If you want all the gen parameters, run /checkparameters with a link to the message containing this image!")
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
  #ignore event from another channel
  if str(message.channel) != auto_channel_name:
      return
  #ignore no attachments message
  if len(message.attachments)==0:
      return
  
  start_time = time.time()
  print(message.attachments)
  await analyzeAllAttachments(message)
  end_time = time.time()
  elapsed_time = end_time - start_time
  print(f"Execution time: {elapsed_time} seconds") 


@client.tree.command(name="ping",
                     description="Check the latency of the bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f'>>> \U0001f3d3 Pong! Client Latency : `{round(client.latency * 1000)}ms`'
    )


@client.tree.command(
    name="checkparameters",
    description=
    "Get Stable Diffusion generation settings and prompts used of an image from a linked message")
async def checkparameters(interaction: discord.Interaction, private_mode: bool,
                          link: str):

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
        if len(message.attachments)==0:
            await interaction.followup.send("There's nothing attached, you know<:TeriDerp:1104059514501746689>?"
                                            , ephemeral=private_mode)
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
                                   file=discord.File(eimageurl),ephemeral=private_mode)


@client.tree.command(name="anonsend",
                     description="Send images anonymously, if you're shy")
async def anonsend(interaction: discord.Interaction,
                          file: discord.Attachment):
    
    try:
        # Get user_id for security
        user_id = interaction.user.id
        # Fetch channnel to BotLogChannel
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
                # For security, output user id  to BotLogChannel
                ml = m.jump_url
                await channel.send(f"User ID {user_id} sent an image anonymously! Jump to message: {ml}")
    except Exception as e:
        print(e)
        eimageurl = "./assets/confused.png"
        await interaction.response.send_message("That file's not an image, or is it?", ephemeral=True 
                                                ,file=discord.File(eimageurl))
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
    #TODO: update the following info to make it relevant and useful now
    @discord.ui.button(label="Get Started",
                       emoji="🚀",
                       style=discord.ButtonStyle.blurple)
    async def get_started_button(self, interaction: discord.Interaction,
                                 button: discord.ui.Button):

        embed1 = discord.Embed(
            title="Requirements and Setting Up Stable Diffusion",
            url=
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
            color=0x0062ff)
        embed1.set_author(name="Mecha Hassaku - Helpdesk",
                          icon_url=client.user.avatar.url)
        embed1.add_field(
            name=":one:  Requirements  :notepad_spiral:",
            value=
            "Minimum Requirements:\n⊛ A > 4/6GB  VRAM GPU (Preferably Nvidia)\n⊛ Atleast 15GB of free disk space\n⊛ Windows 8, preferably 10/11",
            inline=False)
        embed1.add_field(
            name="Don't meet the requirements? Dont Worry!",
            value=
            "You can use these (for free pretty much): https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Online-Services",
            inline=False)
        embed1.add_field(
            name=":two:  Installation  :gear:",
            value=
            "Follow these:\n⊛ Windows: https://github.com/AUTOMATIC1111/stable-diffusion-webui#automatic-installation-on-windows\nVideo guide: https://www.youtube.com/watch?v=3cvP7yJotUM",
            inline=False)
        embed1.add_field(
            name="Too Lazy? Use this unofficial .exe installer for Windows",
            value=
            "https://github.com/EmpireMediaScience/A1111-Web-UI-Installer",
            inline=False)
        embed1.add_field(
            name="Done. Now what?",
            value=
            "By default the SD 1.5 model is installed but you can use many other models like Ikena's Hassaku from civitai.com. Save them to the `stable-diffusion-webui/models/Stable-diffusion` path in your computer",
            inline=False)

        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed1)

    @discord.ui.button(label="Utility",
                       emoji="🔧",
                       style=discord.ButtonStyle.blurple)
    async def utility_button(self, interaction: discord.Interaction,
                             button: discord.ui.Button):

        embed2 = discord.Embed(
            title="Utility Tools & Resources",
            url=
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
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
            value=
            "CivitAI: https://civitai.com\nHuggingFace:https://huggingface.co ",
            inline=False)
        embed2.add_field(
            name="Training tools",
            value=
            "Kohya GUI: https://github.com/bmaltais/kohya_ss\nImage/Dataset Captioning tool: https://github.com/toriato/stable-diffusion-webui-wd14-tagger ",
            inline=False)

        await interaction.response.defer()
        await interaction.edit_original_response(embed=embed2)

    @discord.ui.button(label="Back",
                       emoji="◀️",
                       style=discord.ButtonStyle.danger)
    async def back_button(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        embed = discord.Embed(
            title="MechaHassaku Helpdesk",
            url=
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
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
            value=
            "Use my flagship feature to find out the prompt and generation settings used from an SD AI generated image! Just type `/imageparameters` in the chat box and you will be prompted to upload the image.",
            inline=False)
        embed.add_field(
            name="Check out Ikena's Stable Diffusion models for all your needs: Anime, Hentai & Semi-Realistic",
            value=
            "https://civitai.com/user/Ikena/models \nIf you like his work, consider donating on Patreon\n**Still have questions? Ask away at <#1072336225496739970>**",
            inline=False)

        embed.set_footer(
            text=
            "This is an early version of the bot. If you find something wrong or have suggestions, feel free to contact me (manofculture#0644)"
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
        url=
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL45I7czocaVJmE4FQrV4r6R5SL47hIs-O&index=92",
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
        value=
        "Use my flagship feature to find out the prompt and generation settings used from an SD AI generated image! Just type `/imageparameters` in the text box and you will be prompted to upload the image.",
        inline=False)
    embed.add_field(
            name="Check out Ikena's Stable Diffusion models for all your needs: Anime, Hentai & Semi-Realistic",
            value=
            "https://civitai.com/user/Ikena/models \nIf you like his work, consider donating on Patreon\n**Still have questions? Ask away at <#1072336225496739970>**",
            inline=False)

    embed.set_footer(
        text=
        "This is an early version of the bot. If you find something wrong or have suggestions, feel free to contact me (manofculture#0644)"
    )
    view = helpbclass()
    await interaction.response.send_message(embed=embed, view=view)

        

clienttoken = os.environ["TOKEN"]
client.run(clienttoken)
