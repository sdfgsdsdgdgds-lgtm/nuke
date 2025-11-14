# -*- coding: utf-8 -*-
"""
Discord-bot med:
✅ Auto-roll
✅ Anti-raid
✅ Self-assign-roll
✅ Välkomstmeddelanden
✅ Moderation (kick, ban, timeout)
✅ Uptime
✅ Render Deploy Hook restart
✅ Nuke (endast ägaren)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import aiohttp
import requests

# ==============================
# Keep-alive (Replit)
# ==============================
try:
    from keep_alive import keep_alive
    keep_alive()
except:
    pass

# ==============================
# Miljövariabler
# ==============================
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SELF_ASSIGN_ROLE_NAME = os.getenv("SELF_ASSIGN_ROLE")
DEPLOY_HOOK_URL = os.getenv("DEPLOY_HOOK_URL")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
WELCOME_CHANNEL_NAME = "welcome"

# ==============================
# Intents
# ==============================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================
# Konfiguration
# ==============================
AUTO_ROLE_NAME = "Member"
ANTI_RAID_TIME_WINDOW = 60
ANTI_RAID_THRESHOLD = 5
LOCKDOWN_DURATION = 300
join_times = defaultdict(list)
locked_guilds = set()
start_time = datetime.utcnow()

# ==============================
# Hjälpfunktioner
# ==============================
def format_timedelta(delta: timedelta):
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")
    return " ".join(parts) or "0s"

def check_raid(guild_id):
    now = datetime.now()
    join_times[guild_id] = [t for t in join_times[guild_id] if now - t < timedelta(seconds=ANTI_RAID_TIME_WINDOW)]
    return len(join_times[guild_id]) >= ANTI_RAID_THRESHOLD

async def unlock_guild(guild):
    await asyncio.sleep(LOCKDOWN_DURATION)
    for channel in guild.text_channels:
        try:
            await channel.set_permissions(guild.default_role, send_messages=True)
        except:
            pass
    locked_guilds.discard(guild.id)
    print(f"🔓 {guild.name} upplåst efter raid-skydd.")

# ==============================
# Events
# ==============================
@bot.event
async def on_ready():
    print(f"✅ Inloggad som {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synkroniserade {len(synced)} kommandon.")
    except Exception as e:
        print(f"❌ Sync-fel: {e}")

    if not nightly_restart.is_running():
        nightly_restart.start()

@bot.event
async def on_member_join(member):
    guild = member.guild

    # === Auto-roll ===
    role = discord.utils.get(guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
            print(f"🎉 Gav rollen '{AUTO_ROLE_NAME}' till {member.name}")
        except Exception as e:
            print(f"⚠️ Kunde inte ge roll: {e}")

    # === Welcome ===
    channel = discord.utils.get(guild.text_channels, name=WELCOME_CHANNEL_NAME) or guild.text_channels[0]
    try:
        await channel.send(f"👋 Hej {member.mention}! Välkommen till **{guild.name}**!")
    except:
        pass

    # === Anti-raid ===
    join_times[guild.id].append(datetime.now())
    if check_raid(guild.id) and guild.id not in locked_guilds:
        locked_guilds.add(guild.id)
        alert = discord.utils.get(guild.text_channels, name="admin") or channel
        if alert:
            embed = discord.Embed(
                title="🚨 RAID VARNING 🚨",
                description=f"{ANTI_RAID_THRESHOLD}+ användare gick med inom {ANTI_RAID_TIME_WINDOW}s!",
                color=discord.Color.red(),
            )
            await alert.send(embed=embed)

        for c in guild.text_channels:
            try:
                await c.set_permissions(guild.default_role, send_messages=False)
            except:
                pass

        print("⚠️ Raid upptäckt! Kanaler låsta.")
        bot.loop.create_task(unlock_guild(guild))

# ==============================
# Slash-kommandon
# ==============================
@bot.tree.command(name="hej", description="Säger hej!")
async def hej(interaction: discord.Interaction):
    await interaction.response.send_message(f"👋 Hej {interaction.user.mention}!")

@bot.tree.command(name="ping", description="Visar botens latens")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency*1000)}ms")

@bot.tree.command(name="uptime", description="Visar hur länge boten varit igång")
async def uptime(interaction: discord.Interaction):
    delta = datetime.utcnow() - start_time
    await interaction.response.send_message(f"⏱️ Uptime: **{format_timedelta(delta)}**", ephemeral=True)

@bot.tree.command(name="giveme", description="Ger dig self-assign-rollen")
async def giveme(interaction: discord.Interaction):
    if not SELF_ASSIGN_ROLE_NAME:
        await interaction.response.send_message("❌ Ingen self-assign-roll definierad.", ephemeral=True)
        return
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=SELF_ASSIGN_ROLE_NAME)
    if not role:
        await interaction.response.send_message(f"❌ Rollen '{SELF_ASSIGN_ROLE_NAME}' finns inte.", ephemeral=True)
        return
    if role in interaction.user.roles:
        await interaction.response.send_message(f"⚠️ Du har redan rollen {role.name}.", ephemeral=True)
        return
    try:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"✅ Du fick rollen **{role.name}**!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Kunde inte ge roll: {e}", ephemeral=True)

# ==============================
# Moderation
# ==============================
@bot.tree.command(name="kick", description="Sparkar en användare")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Ingen anledning"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 {member} sparkades. ({reason})")

@bot.tree.command(name="ban", description="Bannar en användare")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Ingen anledning"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 {member} bannades. ({reason})")

@bot.tree.command(name="unban", description="Tar bort en bannlysning")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    user = await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(f"✅ {user} unbannad.")

@bot.tree.command(name="timeout", description="Ger timeout till en användare")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minuter: int, reason: str = "Ingen anledning"):
    until = datetime.utcnow() + timedelta(minutes=minuter)
    await member.timeout(until, reason=reason)
    await interaction.response.send_message(f"⏳ {member.mention} har timeout i {minuter} minuter.")

@bot.tree.command(name="untimeout", description="Tar bort timeout från en användare")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"✅ Timeout borttagen för {member.mention}.")

# ==============================
# Nuke (endast ägare)
# ==============================
@bot.tree.command(name="nuke", description="Raderar alla kanaler och roller (endast ägaren)")
@app_commands.checks.has_permissions(administrator=True)
async def nuke(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Du får inte använda detta kommando.", ephemeral=True)
        return

    guild = interaction.guild
    await interaction.response.send_message("💣 Startar NUKE... detta tar några sekunder.", ephemeral=True)

    # Radera alla kanaler
    for c in guild.channels:
        try:
            await c.delete()
        except:
            pass

    # Radera alla roller utom @everyone
    for role in guild.roles:
        if role.name != "@everyone":
            try:
                await role.delete()
            except:
                pass

    # Skapa ny kanal
    new_channel = await guild.create_text_channel("rebooted-server")
    await new_channel.send("💥 Servern har återställts! (NUKE utförd av ägaren)")

# ==============================
# Automatisk nattlig omstart
# ==============================
@tasks.loop(minutes=1)
async def nightly_restart():
    now = datetime.now()
    if now.hour == 3 and now.minute == 0 and DEPLOY_HOOK_URL:
        print("🕒 Automatisk omstart (Render Deploy Hook)")
        try:
            requests.post(DEPLOY_HOOK_URL)
            print("✅ Deploy Hook kallad.")
        except Exception as e:
            print(f"❌ Kunde inte kalla Deploy Hook: {e}")

# ==============================
# Starta boten
# ==============================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Ingen DISCORD_BOT_TOKEN hittades i miljövariabler.")
    else:
        print("🚀 Startar Discord-bot...")
        bot.run(TOKEN)
