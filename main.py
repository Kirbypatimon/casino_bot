import discord
from discord.ext import commands
import random
import json
import sqlite3
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# SQLite DB 接続
conn = sqlite3.connect("moneybot.db")
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, money INTEGER)")
conn.commit()

# 設定ファイルの読み込み
def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
work_cooldowns = {}

def get_money(user_id):
    c.execute("SELECT money FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    return result[0] if result else 0

def update_money(user_id, amount):
    current = get_money(user_id)
    new_amount = max(0, current + amount)
    c.execute("INSERT OR REPLACE INTO users (user_id, money) VALUES (?, ?)", (user_id, new_amount))
    conn.commit()

def check_rich(ctx):
    if get_money(ctx.author.id) < 10000:
        raise commands.CheckFailure("💰 10000円未満の方は遊べません！")

def admin_only():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        raise commands.CheckFailure("🔒 管理者専用コマンドです。")
    return commands.check(predicate)

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user}")

@bot.command()
async def money(ctx):
    await ctx.send(f"💰 {ctx.author.mention} の所持金：{get_money(ctx.author.id)}円")

@bot.command()
@commands.check(check_rich)
async def slot(ctx):
    cost = config["slot"]["cost"]
    symbols = config["slot"]["symbols"]
    payouts = config["slot"]["payouts"]

    if get_money(ctx.author.id) < cost:
        return await ctx.send("💸 所持金が足りません。")

    result = [random.choice(symbols) for _ in range(3)]
    result_str = "".join(result)
    update_money(ctx.author.id, -cost)

    payout = payouts.get(result_str, 0)
    if payout > 0:
        update_money(ctx.author.id, payout * cost)
        await ctx.send(f"🎰 {result_str}\n🎉 {ctx.author.mention} 勝利！ +{payout * cost}円")
    else:
        await ctx.send(f"🎰 {result_str}\n💔 残念！")

@bot.command()
@commands.check(check_rich)
async def dice(ctx, guess: int):
    if guess < 1 or guess > 6:
        return await ctx.send("🎲 1〜6の数字を指定してください。")
    roll = random.randint(1, 6)
    bet = config["dice"]["bet"]
    if get_money(ctx.author.id) < bet:
        return await ctx.send("💸 所持金が足りません。")
    update_money(ctx.author.id, -bet)

    if roll == guess:
        reward = bet * config["dice"]["multiplier"]
        update_money(ctx.author.id, reward)
        await ctx.send(f"🎲 {roll}！当たり！ +{reward}円")
    else:
        await ctx.send(f"🎲 {roll}！ハズレ！")

@bot.command()
@commands.check(check_rich)
async def br(ctx, guess: str):
    guess = guess.lower()
    bet = config["br"]["bet"]
    if guess not in ["黒", "赤", "白"]:
        return await ctx.send("⚫️か🔴か⚪️を指定してください（例: `/br 赤`）")
    if get_money(ctx.author.id) < bet:
        return await ctx.send("💸 所持金が足りません。")
    update_money(ctx.author.id, -bet)

    roll = random.random()
    result = "白" if roll < config["br"]["white_chance"] else random.choice(["赤", "黒"])

    if guess == result:
        multiplier = config["br"]["white_multiplier"] if result == "白" else config["br"]["red_black_multiplier"]
        reward = bet * multiplier
        update_money(ctx.author.id, reward)
        await ctx.send(f"🎯 結果: {result}！勝ち！ +{reward}円")
    else:
        await ctx.send(f"💥 結果: {result}！負け！")

@bot.command()
@commands.check(check_rich)
async def blackjack(ctx):
    bet = config["blackjack"]["bet"]
    if get_money(ctx.author.id) < bet:
        return await ctx.send("💸 所持金が足りません。")
    update_money(ctx.author.id, -bet)

    player = random.randint(16, 22)
    dealer = random.randint(16, 22)
    msg = f"🃏 あなた: {player} / ディーラー: {dealer}\n"

    if player > 21 or (dealer <= 21 and dealer > player):
        await ctx.send(msg + "💥 あなたの負け！")
    elif player == dealer:
        update_money(ctx.author.id, bet)
        await ctx.send(msg + "🤝 引き分け（返金）")
    else:
        reward = bet * config["blackjack"]["win_multiplier"]
        update_money(ctx.author.id, reward)
        await ctx.send(msg + f"🎉 勝ち！ +{reward}円")

@bot.command()
async def work(ctx):
    user_id = ctx.author.id
    now = asyncio.get_event_loop().time()
    if user_id in work_cooldowns and now - work_cooldowns[user_id] < 3600:
        remaining = int(3600 - (now - work_cooldowns[user_id]))
        return await ctx.send(f"⏳ クールダウン中。あと {remaining // 60}分{remaining % 60}秒")
    work_cooldowns[user_id] = now

    reward = random.randint(config["work"]["min"], config["work"]["max"])
    update_money(user_id, reward)
    await ctx.send(f"💼 {ctx.author.mention} が働いて {reward}円稼いだ！")

@bot.command()
async def ranking(ctx):
    c.execute("SELECT user_id, money FROM users ORDER BY money DESC LIMIT 10")
    rows = c.fetchall()
    msg = "🏆 所持金ランキング:\n"
    for i, (user_id, money) in enumerate(rows):
        user = await bot.fetch_user(user_id)
        msg += f"{i+1}. {user.name}：{money}円\n"
    await ctx.send(msg)

@bot.command()
@admin_only()
async def admin_money(ctx, member: discord.Member, amount: int):
    update_money(member.id, -amount)
    await ctx.send(f"🔻 {member.display_name} のお金を {amount}円 減らしました。")

@bot.command()
@admin_only()
async def remove_money(ctx, member: discord.Member, amount: int):
    update_money(member.id, amount)
    await ctx.send(f"🔺 {member.display_name} に {amount}円 減らしました。")

@bot.command()
@admin_only()
async def slot_set(ctx, key: str, value):
    config["slot"][key] = int(value) if value.isdigit() else value
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    await ctx.send(f"✅ slot設定 `{key}` を `{value}` に変更しました")

@bot.command()
@admin_only()
async def work_set(ctx, min_or_max: str, value: int):
    if min_or_max not in ["min", "max"]:
        return await ctx.send("❌ min か max を指定してください。")
    config["work"][min_or_max] = value
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    await ctx.send(f"✅ work設定 `{min_or_max}` を `{value}` に変更しました")

# .env の TOKEN で起動
from dotenv import load_dotenv
load_dotenv()
bot.run(os.getenv("TOKEN"))
