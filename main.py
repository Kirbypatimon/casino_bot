import discord
from discord import app_commands
from discord.ext import commands
import random
import json
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# SQLiteセットアップ
conn = sqlite3.connect("database.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    money INTEGER DEFAULT 1000,
    last_work TEXT
)
""")
conn.commit()

# 設定読み込み
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# ユーティリティ
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

# 共通チェック：所持金10000円以上
async def check_rich(interaction: discord.Interaction):
    if get_user_money(str(interaction.user.id)) < 10000:
        await interaction.response.send_message("💰 10000円未満の方は遊べません！", ephemeral=True)
        return False
    return True

# エラーハンドラ
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(str(error), ephemeral=True)
    else:
        raise error

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send(str(error))
    else:
        raise error

# === コマンド群 ===

# /money
@tree.command(name="money", description="所持金を確認します")
async def money(interaction: discord.Interaction):
    money = get_user_money(str(interaction.user.id))
    await interaction.response.send_message(f"💰 {interaction.user.mention} の所持金は {money}円 です。")

# /work
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
            seconds = remaining.seconds % 60
            await interaction.response.send_message(f"🕒 次の労働まで {minutes}分{seconds}秒待ってください。", ephemeral=True)
            return

    min_w = config["work"]["min"]
    max_w = config["work"]["max"]
    amount = random.randint(min_w, max_w)
    update_user_money(user_id, amount)
    c.execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now.isoformat(), user_id))
    conn.commit()
    await interaction.response.send_message(f"🛠️ {interaction.user.mention} は {amount}円 を稼ぎました！")

# /work-set min|max value 管理者専用
@tree.command(name="work-set", description="workの最低/最高報酬を設定します（管理者専用）")
@app_commands.describe(minmax="minかmax", value="設定値（整数）")
async def work_set(interaction: discord.Interaction, minmax: str, value: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    if minmax not in ["min", "max"]:
        await interaction.response.send_message("❌ minかmaxを指定してください。", ephemeral=True)
        return
    config["work"][minmax] = value
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    await interaction.response.send_message(f"✅ workの{minmax}を{value}に設定しました。")

# /slot
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

# /slot-set 管理者専用 確率・倍率・絵柄変更
@tree.command(name="slot-set", description="スロット設定変更（管理者専用）")
@app_commands.describe(symbols="絵文字5個（例: 🍒🍋🍇⭐💎）", payout_json="JSON形式の倍率（例: {\"🍒🍒🍒\":5})", cost="掛け金")
async def slot_set(interaction: discord.Interaction, symbols: str, payout_json: str, cost: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    try:
        new_symbols = [s for s in symbols if s.strip()]
        if len(new_symbols) != 5:
            await interaction.response.send_message("❌ 絵文字は5つ指定してください。", ephemeral=True)
            return
        new_payouts = json.loads(payout_json)
        config["slot"]["symbols"] = new_symbols
        config["slot"]["payouts"] = new_payouts
        config["slot"]["cost"] = cost
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        await interaction.response.send_message("✅ スロット設定を更新しました。")
    except Exception as e:
        await interaction.response.send_message(f"❌ エラー: {e}", ephemeral=True)

# /blackjack
@tree.command(name="blackjack", description="ブラックジャックで遊べます")
@app_commands.check(check_rich)
async def blackjack(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    bj_cfg = config["blackjack"]
    bet = bj_cfg.get("bet", 2000)

    if get_user_money(user_id) < bet:
        await interaction.response.send_message("❌ 所持金が足りません。", ephemeral=True)
        return

    update_user_money(user_id, -bet)

    player_score = random.randint(16, 22)
    dealer_score = random.randint(16, 22)

    if player_score > 21:
        msg = f"あなた: {player_score} (バースト)\nディーラー: {dealer_score}\n💥 あなたの負けです！"
    elif dealer_score > 21 or player_score > dealer_score:
        reward = int(bet * bj_cfg.get("win_multiplier", 2))
        update_user_money(user_id, reward)
        msg = f"あなた: {player_score}\nディーラー: {dealer_score}\n🎉 あなたの勝ち！ +{reward}円"
    elif player_score == dealer_score:
        update_user_money(user_id, bet)  # 返金
        msg = f"あなた: {player_score}\nディーラー: {dealer_score}\n🤝 引き分け（返金）"
    else:
        msg = f"あなた: {player_score}\nディーラー: {dealer_score}\n😭 あなたの負けです！"

    await interaction.response.send_message(msg)

# /dice 1~6の数字を当てる
@tree.command(name="dice", description="1〜6の数字を当てるゲーム")
@app_commands.describe(guess="1から6の数字を選んでください")
@app_commands.check(check_rich)
async def dice(interaction: discord.Interaction, guess: int):
    if guess < 1 or guess > 6:
        await interaction.response.send_message("❌ 1から6の数字を入力してください。", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    bet = config["dice"].get("bet", 500)
    if get_user_money(user_id) < bet:
        await interaction.response.send_message("❌ 所持金が足りません。", ephemeral=True)
        return

    update_user_money(user_id, -bet)
    roll = random.randint(1, 6)
    multiplier = config["dice"].get("multiplier", 5)

    if guess == roll:
        reward = bet * multiplier
        update_user_money(user_id, reward)
        await interaction.response.send_message(f"🎲 サイコロの目は {roll}！当たり！ +{reward}円")
    else:
        await interaction.response.send_message(f"🎲 サイコロの目は {roll}。残念、不正解。")

# /br 黒/赤/白当て
@tree.command(name="br", description="黒・赤・白を当てるゲーム")
@app_commands.describe(choice="黒か赤か白を選んでください")
@app_commands.check(check_rich)
async def br(interaction: discord.Interaction, choice: str):
    choice = choice.lower()
    if choice not in ["黒", "赤", "白"]:
        await interaction.response.send_message("❌ 黒、赤、白のいずれかを入力してください。", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    bet = config["br"].get("bet", 1000)
    if get_user_money(user_id) < bet:
        await interaction.response.send_message("❌ 所持金が足りません。", ephemeral=True)
        return

    update_user_money(user_id, -bet)

    # 色の決定（白は低確率）
    white_chance = config["br"].get("white_chance", 0.05)
    roll = random.random()
    if roll < white_chance:
        result = "白"
    else:
        result = random.choice(["黒", "赤"])

    if choice == result:
        if result == "白":
            reward = bet * config["br"].get("white_multiplier", 10)
        else:
            reward = bet * config["br"].get("red_black_multiplier", 2)
        update_user_money(user_id, reward)
        await interaction.response.send_message(f"🎯 結果は{result}！当たり！ +{reward}円")
    else:
        await interaction.response.send_message(f"🎯 結果は{result}。残念、不正解。")

# /ranking 所持金トップ10表示
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

# /admin-money 管理者専用 所持金減らす
@tree.command(name="admin-money", description="指定ユーザーの所持金を減らす（管理者専用）")
@app_commands.describe(user="ユーザー", amount="減らす金額（正の整数）")
async def admin_money(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ 金額は正の整数で指定してください。", ephemeral=True)
        return
    user_id = str(user.id)
    update_user_money(user_id, -amount)
    await interaction.response.send_message(f"✅ {user.mention} の所持金を {amount}円 減らしました。")

# /remove-money 管理者専用 所持金増やす
@tree.command(name="remove-money", description="指定ユーザーの所持金を増やす（管理者専用）")
@app_commands.describe(user="ユーザー", amount="増やす金額（正の整数）")
async def remove_money(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ 金額は正の整数で指定してください。", ephemeral=True)
        return
    user_id = str(user.id)
    update_user_money(user_id, amount)
    await interaction.response.send_message(f"✅ {user.mention} の所持金を {amount}円 増やしました。")

# --- 起動時同期 ---
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
