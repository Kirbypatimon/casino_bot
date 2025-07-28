import discord
from discord import app_commands
from discord.ext import commands
import random
import json
import sqlite3
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# SQLite接続
conn = sqlite3.connect("database.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    money INTEGER DEFAULT 1000,
    last_work TEXT
)""")
conn.commit()

# 設定ファイルロード
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# ユーティリティ関数
def get_user_money(user_id: str) -> int:
    c.execute("SELECT money FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        return row[0]
    else:
        c.execute("INSERT INTO users (user_id, money) VALUES (?, ?)", (user_id, 1000))
        conn.commit()
        return 1000

def update_user_money(user_id: str, amount: int):
    current = get_user_money(user_id)
    new_amount = max(0, current + amount)
    c.execute("REPLACE INTO users (user_id, money) VALUES (?, ?)", (user_id, new_amount))
    conn.commit()

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

# チェック関数
async def check_rich(interaction: discord.Interaction):
    if get_user_money(str(interaction.user.id)) < 10000:
        await interaction.response.send_message("💰 10000円未満の方は遊べません！", ephemeral=True)
        return False
    return True

# エラーハンドラー（スラッシュコマンド用）
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(str(error), ephemeral=True)
    else:
        # それ以外は標準処理に任せる
        raise error

# エラーハンドラー（テキストコマンド用）
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send(str(error))
    else:
        raise error

# コマンド群

@tree.command(name="money", description="所持金を確認します")
async def money(interaction: discord.Interaction):
    money = get_user_money(str(interaction.user.id))
    await interaction.response.send_message(f"💰 {interaction.user.mention} の所持金は {money}円 です。")

@tree.command(name="work", description="1時間に1回お金を稼げます")
async def work(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = datetime.utcnow()

    c.execute("SELECT last_work FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        last_work = datetime.fromisoformat(row[0])
        if now - last_work < timedelta(hours=1):
            remaining = timedelta(hours=1) - (now - last_work)
            minutes = remaining.seconds // 60
            await interaction.response.send_message(f"🕒 次の労働まで {minutes} 分待ってください。", ephemeral=True)
            return

    amount = random.randint(config["work"]["min"], config["work"]["max"])
    update_user_money(user_id, amount)
    c.execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now.isoformat(), user_id))
    conn.commit()
    await interaction.response.send_message(f"🛠️ {interaction.user.mention} は {amount}円 を稼ぎました！")

@tree.command(name="slot", description="スロットを回して777を狙え！")
@app_commands.check(check_rich)
async def slot(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    slot_cfg = config["slot"]
    cost = slot_cfg.get("cost", 1000)

    if get_user_money(user_id) < cost:
        await interaction.response.send_message("❌ 所持金が足りません。", ephemeral=True)
        return

    update_user_money(user_id, -cost)
    symbols = slot_cfg["symbols"]
    result = [random.choice(symbols) for _ in range(3)]
    result_str = " | ".join(result)

    result_key = "".join(result)
    payout_multiplier = slot_cfg["payouts"].get(result_key, 0)
    reward = payout_multiplier * cost

    if reward > 0:
        update_user_money(user_id, reward)
        await interaction.response.send_message(f"🎰 `{result_str}`\n🎉 当たり！ {reward}円ゲット！（倍率: x{payout_multiplier}）")
    else:
        await interaction.response.send_message(f"🎰 `{result_str}`\n💀 はずれ！")

@tree.command(name="ranking", description="所持金のトップ10を表示します")
async def ranking(interaction: discord.Interaction):
    c.execute("SELECT user_id, money FROM users ORDER BY money DESC LIMIT 10")
    top = c.fetchall()
    embed = discord.Embed(title="🏆 所持金ランキング", color=0xFFD700)
    for idx, (user_id, money) in enumerate(top, start=1):
        try:
            user = await bot.fetch_user(int(user_id))
            name = user.name
        except:
            name = "Unknown"
        embed.add_field(name=f"{idx}位: {name}", value=f"{money}円", inline=False)
    await interaction.response.send_message(embed=embed)

# 管理者用slot-setコマンド例
@tree.command(name="slot-set", description="スロットの設定変更（管理者専用）")
@app_commands.describe(symbols="絵文字5個（例: 🍒🍋🍇⭐💎）", payout_json="JSON形式の倍率（例: {\"🍒🍒🍒\":5})")
async def slot_set(interaction: discord.Interaction, symbols: str, payout_json: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    try:
        new_symbols = [s for s in symbols if s.strip()]
        new_payouts = json.loads(payout_json)
        if len(new_symbols) != 5:
            await interaction.response.send_message("❌ 絵文字は5つ指定してください。", ephemeral=True)
            return
        config["slot"]["symbols"] = new_symbols
        config["slot"]["payouts"] = new_payouts
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        await interaction.response.send_message("✅ スロット設定を更新しました。")
    except Exception as e:
        await interaction.response.send_message(f"❌ エラー: {e}", ephemeral=True)

# Bot起動時にスラッシュコマンド同期
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
