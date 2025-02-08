import discord
from discord import app_commands
from discord.ext import commands
import json
import sqlite3
import random
import string
import os
from datetime import datetime, timedelta
import aiosqlite
import io
from dotenv import load_dotenv

# Load configuration
load_dotenv()

with open('config.json', 'r') as f:
    config = json.load(f)
    config['token'] = os.getenv('DISCORD_TOKEN')

if not config['token']:
    raise ValueError("No Discord token found. Please set DISCORD_TOKEN in your .env file.")

ADMIN_ROLE_NAME = "Admin"

class CreditBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(command_prefix='!', intents=intents)
        self.db_path = 'data/credit_system.db'
        self.products = {}
        self.config = config
        self.setup_database()

    async def setup_hook(self):
        # First load the product manager extension
        try:
            await self.load_extension('product_manager')
            print("Loaded product_manager extension")
        except Exception as e:
            print(f"Failed to load product_manager: {e}")

    def setup_database(self):
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                    (user_id INTEGER PRIMARY KEY,
                     credits INTEGER DEFAULT 0,
                     is_blacklisted BOOLEAN DEFAULT 0)''')
        
        # Create codes table
        c.execute('''CREATE TABLE IF NOT EXISTS codes
                    (code TEXT PRIMARY KEY,
                     credits INTEGER,
                     is_used BOOLEAN DEFAULT 0)''')
                     
        # Create products table
        c.execute('''CREATE TABLE IF NOT EXISTS products
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT,
                     price INTEGER,
                     file_path TEXT)''')
                     
        # Create transactions table
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     purchase_id TEXT UNIQUE,
                     user_id INTEGER,
                     product_id INTEGER,
                     amount INTEGER,
                     original_cost INTEGER,
                     discount_amount INTEGER DEFAULT 0,
                     discount_code TEXT,
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        # Create discount_codes table
        c.execute('''CREATE TABLE IF NOT EXISTS discount_codes
                    (code TEXT PRIMARY KEY,
                     discount_amount INTEGER,
                     discount_type TEXT,
                     is_used BOOLEAN DEFAULT 0,
                     max_uses INTEGER DEFAULT 1,
                     uses_left INTEGER,
                     expiry_date DATETIME)''')
        
        conn.commit()
        conn.close()

bot = CreditBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('Connected to guilds:')
    
    # Define all commands
    commands = [
        {
            "name": "balance",
            "description": "Check your credit balance"
        },
        {
            "name": "add_credits",
            "description": "[Admin] Add credits to a user",
            "default_member_permissions": "8",  # Administrator permission
            "options": [
                {
                    "name": "user",
                    "description": "The user to add credits to",
                    "type": 6,
                    "required": True
                },
                {
                    "name": "amount",
                    "description": "Amount of credits to add",
                    "type": 4,
                    "required": True
                }
            ]
        },
        {
            "name": "redeem",
            "description": "Redeem a code for credits",
            "options": [
                {
                    "name": "code",
                    "description": "The code to redeem",
                    "type": 3,
                    "required": True
                }
            ]
        },
        {
            "name": "blacklist",
            "description": "[Admin] Blacklist a user",
            "default_member_permissions": "8",
            "options": [
                {
                    "name": "user",
                    "description": "The user to blacklist",
                    "type": 6,
                    "required": True
                }
            ]
        },
        {
            "name": "unblacklist",
            "description": "[Admin] Remove a user from blacklist",
            "default_member_permissions": "8",
            "options": [
                {
                    "name": "user",
                    "description": "The user to unblacklist",
                    "type": 6,
                    "required": True
                }
            ]
        },
        {
            "name": "blacklist_status",
            "description": "[Admin] Check if a user is blacklisted",
            "default_member_permissions": "8",
            "options": [
                {
                    "name": "user",
                    "description": "The user to check",
                    "type": 6,
                    "required": True
                }
            ]
        },
        {
            "name": "stock",
            "description": "View available products and their stock"
        },
        {
            "name": "purchase",
            "description": "Purchase a product",
            "options": [
                {
                    "name": "quantity",
                    "description": "Amount to purchase",
                    "type": 4,
                    "required": True
                }
            ]
        }
    ]

    try:
        print("Starting to sync commands...")
        # Register commands for each guild
        for guild_id in config['guild_ids']:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {guild_id}")
            
        print("Command sync complete!")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    for guild in bot.guilds:
        print(f'- {guild.name} (ID: {guild.id})')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(f"You need the '{ADMIN_ROLE_NAME}' role to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An error occurred: {str(error)}", ephemeral=True)
        print(f"Command error: {str(error)}")

# Admin commands
@bot.tree.command(name="add_credits", description="[Admin] Add credits to a user")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def add_credits(interaction: discord.Interaction, user: discord.Member, amount: int):
    async with aiosqlite.connect(bot.db_path) as db:
        await db.execute('INSERT OR IGNORE INTO users (user_id, credits) VALUES (?, 0)', (user.id,))
        await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?', (amount, user.id))
        await db.commit()
    
    await interaction.response.send_message(f"Added {amount} credits to {user.mention}'s account!", ephemeral=True)

@bot.tree.command(name="check_balance", description="[Admin] Check a user's balance")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def check_balance(interaction: discord.Interaction, user: discord.Member):
    async with aiosqlite.connect(bot.db_path) as db:
        async with db.execute('SELECT credits FROM users WHERE user_id = ?', (user.id,)) as cursor:
            result = await cursor.fetchone()
            credits = result[0] if result else 0
    
    await interaction.response.send_message(f"{user.mention}'s balance: {credits} credits", ephemeral=True)

@bot.tree.command(name="generate_code", description="[Admin] Generate redeemable codes")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def generate_code(interaction: discord.Interaction, credits: int, amount: int = 1):
    if amount < 1 or amount > 50:  # Limit to 50 codes at once to prevent abuse
        await interaction.response.send_message("Please generate between 1 and 50 codes at a time.", ephemeral=True)
        return
        
    codes = []
    async with aiosqlite.connect(bot.db_path) as db:
        for _ in range(amount):
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
                # Check if code already exists
                async with db.execute('SELECT 1 FROM codes WHERE code = ?', (code,)) as cursor:
                    if not await cursor.fetchone():
                        break
            
            codes.append(code)
            await db.execute('INSERT INTO codes (code, credits) VALUES (?, ?)', (code, credits))
        await db.commit()
    
    # Format the response
    if amount == 1:
        message = f"Generated code: {codes[0]} worth {credits} credits"
    else:
        message = f"Generated {amount} codes worth {credits} credits each:\n"
        message += "\n".join(codes)
        
        # If the message is too long, send as a file
        if len(message) > 2000:
            file_content = f"Generated codes worth {credits} credits each:\n" + "\n".join(codes)
            file = discord.File(
                io.StringIO(file_content),
                filename=f"generated_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            await interaction.response.send_message(
                f"Generated {amount} codes. Check the attached file.",
                file=file,
                ephemeral=True
            )
            return
    
    await interaction.response.send_message(message, ephemeral=True)

@bot.tree.command(name="blacklist", description="[Admin] Blacklist a user")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def blacklist(interaction: discord.Interaction, user: discord.Member):
    async with aiosqlite.connect(bot.db_path) as db:
        await db.execute('INSERT OR REPLACE INTO users (user_id, is_blacklisted) VALUES (?, 1)', (user.id,))
        await db.commit()
    
    await interaction.response.send_message(f"{user.mention} has been blacklisted.", ephemeral=True)

@bot.tree.command(name="unblacklist", description="[Admin] Remove a user from blacklist")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def unblacklist(interaction: discord.Interaction, user: discord.Member):
    async with aiosqlite.connect(bot.db_path) as db:
        # Check if user is blacklisted
        async with db.execute('SELECT is_blacklisted FROM users WHERE user_id = ?', (user.id,)) as cursor:
            result = await cursor.fetchone()
            if not result or not result[0]:
                await interaction.response.send_message(f"{user.mention} is not blacklisted.", ephemeral=True)
                return
        
        # Remove blacklist
        await db.execute('UPDATE users SET is_blacklisted = 0 WHERE user_id = ?', (user.id,))
        await db.commit()
    
    await interaction.response.send_message(f"{user.mention} has been removed from the blacklist.", ephemeral=True)

@bot.tree.command(name="blacklist_status", description="[Admin] Check if a user is blacklisted")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def blacklist_status(interaction: discord.Interaction, user: discord.Member):
    async with aiosqlite.connect(bot.db_path) as db:
        async with db.execute('SELECT is_blacklisted FROM users WHERE user_id = ?', (user.id,)) as cursor:
            result = await cursor.fetchone()
            is_blacklisted = result[0] if result else False
    
    status = "is" if is_blacklisted else "is not"
    await interaction.response.send_message(f"{user.mention} {status} blacklisted.", ephemeral=True)

@bot.tree.command(name="purchase_info", description="[Admin] View details of a purchase by ID")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def purchase_info(interaction: discord.Interaction, purchase_id: str):
    async with aiosqlite.connect(bot.db_path) as db:
        # Get transaction details
        query = '''
            SELECT 
                t.purchase_id,
                t.amount,
                t.timestamp,
                p.name as product_name,
                p.price,
                u.user_id
            FROM transactions t
            JOIN products p ON t.product_id = p.id
            JOIN users u ON t.user_id = u.user_id
            WHERE t.purchase_id = ?
        '''
        
        async with db.execute(query, (purchase_id,)) as cursor:
            result = await cursor.fetchone()
            
            if not result:
                await interaction.response.send_message(f"No purchase found with ID: {purchase_id}", ephemeral=True)
                return
            
            purchase_id, amount, timestamp, product_name, price, user_id = result
            
            # Get user mention
            user = interaction.guild.get_member(user_id)
            user_mention = user.mention if user else f"User ID: {user_id}"
            
            # Format timestamp
            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            formatted_time = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            
            # Create embed
            embed = discord.Embed(
                title=f"Purchase Information - {purchase_id}",
                color=discord.Color.blue(),
                timestamp=dt
            )
            
            embed.add_field(name="Customer", value=user_mention, inline=False)
            embed.add_field(name="Product", value=product_name, inline=True)
            embed.add_field(name="Quantity", value=str(amount), inline=True)
            embed.add_field(name="Price per Unit", value=f"{price} credits", inline=True)
            embed.add_field(name="Total Cost", value=f"{price * amount} credits", inline=True)
            embed.add_field(name="Purchase Time", value=formatted_time, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="user_purchases", description="[Admin] View all purchases by a user")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def user_purchases(interaction: discord.Interaction, user: discord.Member):
    async with aiosqlite.connect(bot.db_path) as db:
        query = '''
            SELECT 
                t.purchase_id,
                t.amount,
                t.timestamp,
                p.name as product_name,
                p.price
            FROM transactions t
            JOIN products p ON t.product_id = p.id
            WHERE t.user_id = ?
            ORDER BY t.timestamp DESC
            LIMIT 10
        '''
        
        async with db.execute(query, (user.id,)) as cursor:
            purchases = await cursor.fetchall()
            
            if not purchases:
                await interaction.response.send_message(f"No purchases found for {user.mention}", ephemeral=True)
                return
            
            # Create embed
            embed = discord.Embed(
                title=f"Recent Purchases - {user.display_name}",
                description="Last 10 purchases",
                color=discord.Color.blue()
            )
            
            for purchase in purchases:
                purchase_id, amount, timestamp, product_name, price = purchase
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                formatted_time = dt.strftime('%Y-%m-%d %I:%M:%S %p')
                
                value = f"Product: {product_name}\n"
                value += f"Quantity: {amount}\n"
                value += f"Total Cost: {price * amount} credits\n"
                value += f"Time: {formatted_time}"
                
                embed.add_field(
                    name=f"Purchase ID: {purchase_id}",
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="my_purchases", description="View your purchase history")
async def my_purchases(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.db_path) as db:
        query = '''
            SELECT 
                t.purchase_id,
                t.amount,
                t.timestamp,
                p.name as product_name,
                p.price
            FROM transactions t
            JOIN products p ON t.product_id = p.id
            WHERE t.user_id = ?
            ORDER BY t.timestamp DESC
            LIMIT 5
        '''
        
        async with db.execute(query, (interaction.user.id,)) as cursor:
            purchases = await cursor.fetchall()
            
            if not purchases:
                await interaction.response.send_message("You haven't made any purchases yet!", ephemeral=True)
                return
            
            # Create embed
            embed = discord.Embed(
                title="Your Recent Purchases",
                description="Last 5 purchases",
                color=discord.Color.green()
            )
            
            for purchase in purchases:
                purchase_id, amount, timestamp, product_name, price = purchase
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                formatted_time = dt.strftime('%Y-%m-%d %I:%M:%S %p')
                
                value = f"Product: {product_name}\n"
                value += f"Quantity: {amount}\n"
                value += f"Total Cost: {price * amount} credits\n"
                value += f"Time: {formatted_time}"
                
                embed.add_field(
                    name=f"Purchase ID: {purchase_id}",
                    value=value,
                    inline=False
                )
            
            embed.set_footer(text="Keep your Purchase IDs for reference if you need support!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

# User commands
@bot.tree.command(name="balance", description="Check your credit balance")
async def balance(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.db_path) as db:
        async with db.execute('SELECT credits FROM users WHERE user_id = ?', (interaction.user.id,)) as cursor:
            result = await cursor.fetchone()
            credits = result[0] if result else 0
    
    await interaction.response.send_message(f"Your balance: {credits} credits", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem a code for credits")
async def redeem(interaction: discord.Interaction, code: str):
    async with aiosqlite.connect(bot.db_path) as db:
        # Check if code exists and is unused
        async with db.execute('SELECT credits FROM codes WHERE code = ? AND is_used = 0', (code,)) as cursor:
            result = await cursor.fetchone()
            
            if not result:
                await interaction.response.send_message("Invalid or already used code!", ephemeral=True)
                return
                
            credits = result[0]
            
            # Mark code as used and add credits to user
            await db.execute('UPDATE codes SET is_used = 1 WHERE code = ?', (code,))
            await db.execute('INSERT OR IGNORE INTO users (user_id, credits) VALUES (?, 0)', (interaction.user.id,))
            await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?', (credits, interaction.user.id))
            await db.commit()
    
    await interaction.response.send_message(f"Successfully redeemed {credits} credits!", ephemeral=True)

@bot.tree.command(name="create_discount", description="[Admin] Create a discount code")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def create_discount(
    interaction: discord.Interaction,
    code: str,
    amount: int,
    discount_type: str,
    max_uses: int = 1,
    days_valid: int = 30
):
    # Validate discount type
    if discount_type.upper() not in ['FIXED', 'PERCENT']:
        await interaction.response.send_message(
            "Discount type must be either 'FIXED' or 'PERCENT'",
            ephemeral=True
        )
        return

    # For percentage discounts, validate the amount
    if discount_type.upper() == 'PERCENT' and (amount < 1 or amount > 100):
        await interaction.response.send_message(
            "Percentage discount must be between 1 and 100",
            ephemeral=True
        )
        return

    # Calculate expiry date
    expiry_date = datetime.now().replace(microsecond=0) + timedelta(days=days_valid)

    async with aiosqlite.connect(bot.db_path) as db:
        try:
            await db.execute('''
                INSERT INTO discount_codes 
                (code, discount_amount, discount_type, max_uses, uses_left, expiry_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (code.upper(), amount, discount_type.upper(), max_uses, max_uses, expiry_date))
            await db.commit()

            discount_text = f"{amount}% off" if discount_type.upper() == 'PERCENT' else f"{amount} credits off"
            await interaction.response.send_message(
                f"Created discount code: {code.upper()}\n"
                f"Discount: {discount_text}\n"
                f"Max uses: {max_uses}\n"
                f"Expires: {expiry_date}",
                ephemeral=True
            )
        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "A discount code with this name already exists!",
                ephemeral=True
            )

@bot.tree.command(name="list_discounts", description="[Admin] List all discount codes")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def list_discounts(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.db_path) as db:
        async with db.execute('''
            SELECT code, discount_amount, discount_type, uses_left, expiry_date
            FROM discount_codes
            WHERE expiry_date > CURRENT_TIMESTAMP
            AND uses_left > 0
        ''') as cursor:
            codes = await cursor.fetchall()

    if not codes:
        await interaction.response.send_message("No active discount codes found.", ephemeral=True)
        return

    embed = discord.Embed(title="Active Discount Codes", color=discord.Color.blue())
    
    for code, amount, type, uses, expiry in codes:
        discount = f"{amount}% off" if type == 'PERCENT' else f"{amount} credits off"
        embed.add_field(
            name=code,
            value=f"Discount: {discount}\nUses left: {uses}\nExpires: {expiry}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove_discount", description="[Admin] Remove a discount code")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def remove_discount(interaction: discord.Interaction, code: str):
    async with aiosqlite.connect(bot.db_path) as db:
        await db.execute('DELETE FROM discount_codes WHERE code = ?', (code.upper(),))
        await db.commit()

    await interaction.response.send_message(
        f"Removed discount code: {code.upper()}",
        ephemeral=True
    )

# Run the bot
try:
    bot.run(config['token'], log_handler=None)
except discord.LoginFailure as e:
    print(f"Failed to login: {e}")
    print("Please check if your token is valid and properly configured in config.json")
except Exception as e:
    print(f"An error occurred: {e}") 