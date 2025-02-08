import discord
from discord import app_commands
from discord.ext import commands
import os
import shutil
import aiosqlite
import json
import random
import math
import string
import io

ADMIN_ROLE_NAME = "Admin"

class ProductManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_ids = [int(guild_id) for guild_id in bot.config['guild_ids']]
        self.ensure_product_directory()

    def ensure_product_directory(self):
        if not os.path.exists('products'):
            os.makedirs('products')

    async def count_lines_in_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return sum(1 for line in f if line.strip())
        except:
            return 0

    async def get_and_remove_lines(self, file_path, num_lines):
        """Get lines from file but don't remove them until confirmed"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Filter out empty lines
            lines = [line for line in lines if line.strip()]
            
            if len(lines) < num_lines:
                return None, None

            # Get the lines we want to send
            lines_to_send = lines[:num_lines]
            remaining_lines = lines[num_lines:]

            return lines_to_send, remaining_lines
        except:
            return None, None

    async def remove_lines(self, file_path, remaining_lines):
        """Actually remove the lines from file"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(remaining_lines)
            return True
        except:
            return False

    async def notify_stock_empty(self, product_name: str):
        """Send notification to all admins when stock reaches 0"""
        # Send notifications to admins in all configured guilds
        for guild_id in self.guild_ids:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
                
            admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
            if not admin_role:
                continue
                
            # Get all members with admin role
            admin_members = [member for member in guild.members if admin_role in member.roles]
            
            # Send DM to each admin
            notification = f"⚠️ Alert: Stock for '{product_name}' has reached 0!"
            for admin in admin_members:
                try:
                    await admin.send(notification)
                except:
                    pass  # Skip if can't DM

    @app_commands.command(name="add_product", description="[Admin] Add a new product")
    @app_commands.checks.has_role(ADMIN_ROLE_NAME)
    async def add_product(self, interaction: discord.Interaction, name: str, price: int, stock: int = 0):
        # Defer the response since we'll be waiting for the file
        await interaction.response.defer(ephemeral=True)
        
        # Send a follow-up asking for the file
        await interaction.followup.send("Please upload the product file in your next message.", ephemeral=True)
        
        def check(m):
            return m.author == interaction.user and len(m.attachments) > 0
        
        try:
            # Wait for a message with an attachment
            message = await self.bot.wait_for('message', timeout=60.0, check=check)
            attachment = message.attachments[0]
            file_path = f"products/{attachment.filename}"
            
            # Download the file
            await attachment.save(file_path)
            
            # Add to database
            async with aiosqlite.connect(self.bot.db_path) as db:
                try:
                    await db.execute(
                        'INSERT INTO products (name, price, file_path, stock) VALUES (?, ?, ?, ?)',
                        (name, price, file_path, stock)
                    )
                    await db.commit()
                except Exception as e:
                    # If the stock column doesn't exist, create it and try again
                    if 'no column named stock' in str(e):
                        await db.execute('ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 0')
                        await db.commit()
                        await db.execute(
                            'INSERT INTO products (name, price, file_path, stock) VALUES (?, ?, ?, ?)',
                            (name, price, file_path, stock)
                        )
                        await db.commit()
            
            await interaction.followup.send(f"Added product {name} for {price} credits with {stock} stock!", ephemeral=True)
            
            # Delete the message with the file for security
            try:
                await message.delete()
            except:
                pass
                
        except TimeoutError:
            await interaction.followup.send("Timeout: No file was uploaded. Please try again.", ephemeral=True)

    @app_commands.command(name="remove_product", description="[Admin] Remove a product")
    @app_commands.checks.has_role(ADMIN_ROLE_NAME)
    async def remove_product(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.bot.db_path) as db:
            async with db.execute('SELECT id, name FROM products ORDER BY name') as cursor:
                products = await cursor.fetchall()

        if not products:
            await interaction.response.send_message("No products available to remove!", ephemeral=True)
            return

        # Create selection menu
        options = [discord.SelectOption(label=name, value=str(id)) for id, name in products]
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Choose a product to remove", options=options)

        async def select_callback(interaction: discord.Interaction):
            product_id = int(select.values[0])
            
            async with aiosqlite.connect(self.bot.db_path) as db:
                # Get product details first
                async with db.execute('SELECT name, file_path FROM products WHERE id = ?', (product_id,)) as cursor:
                    result = await cursor.fetchone()
                    if not result:
                        await interaction.response.send_message("Product not found!", ephemeral=True)
                        return
                    
                    name, file_path = result
                    
                    # Remove from database
                    await db.execute('DELETE FROM products WHERE id = ?', (product_id,))
                    await db.commit()
                    
                    # Remove associated files
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    
                    # Remove any stock files
                    stock_dir = f"products/stock_{product_id}"
                    if os.path.exists(stock_dir):
                        shutil.rmtree(stock_dir)

            await interaction.response.send_message(f"Successfully removed product: {name}", ephemeral=True)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Select a product to remove:", view=view, ephemeral=True)

    @app_commands.command(name="stock", description="View available products and their stock")
    async def stock(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.bot.db_path) as db:
            # First, ensure the stock column exists
            try:
                await db.execute('ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 0')
                await db.commit()
            except:
                pass  # Column already exists
                
            async with db.execute('SELECT name, price, stock FROM products ORDER BY name') as cursor:
                products = await cursor.fetchall()

        if not products:
            await interaction.response.send_message("No products available!", ephemeral=True)
            return

        # Format the product list in the requested format
        product_list = []
        for name, price, stock in products:
            stock_count = stock if stock is not None else 0  # Handle NULL values
            product_list.append(f"{name}:\nStock: {stock_count} | Credits: {price}")
        
        formatted_list = "\n\n".join(product_list)
        await interaction.response.send_message(f"Available Products:\n\n{formatted_list}", ephemeral=True)

    @app_commands.command(name="restock", description="[Admin] Restock a product with a stock file")
    @app_commands.checks.has_role(ADMIN_ROLE_NAME)
    async def restock(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.bot.db_path) as db:
            async with db.execute('SELECT id, name, stock FROM products ORDER BY name') as cursor:
                products = await cursor.fetchall()

        if not products:
            await interaction.response.send_message("No products available to restock!", ephemeral=True)
            return

        options = [discord.SelectOption(label=f"{name} (Current Stock: {stock})", value=str(id))
                  for id, name, stock in products]
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Choose a product to restock", options=options)

        async def select_callback(interaction: discord.Interaction):
            product_id = int(select.values[0])
            
            await interaction.response.send_message(
                "Please upload the stock file. Each line in the file will count as 1 stock.",
                ephemeral=True
            )
            
            def check(m):
                return m.author == interaction.user and len(m.attachments) > 0
            
            try:
                message = await self.bot.wait_for('message', timeout=60.0, check=check)
                attachment = message.attachments[0]
                
                # Save the stock file
                stock_file = f"products/stock_{product_id}.txt"
                await attachment.save(stock_file)
                
                # Count lines (stock)
                stock_count = await self.count_lines_in_file(stock_file)
                
                if stock_count == 0:
                    await interaction.followup.send("The file appears to be empty!", ephemeral=True)
                    os.remove(stock_file)
                    return
                
                # Update database
                async with aiosqlite.connect(self.bot.db_path) as db:
                    await db.execute(
                        'UPDATE products SET stock = stock + ? WHERE id = ?',
                        (stock_count, product_id)
                    )
                    await db.commit()
                    
                    # Get updated stock and name
                    async with db.execute(
                        'SELECT name, stock FROM products WHERE id = ?',
                        (product_id,)
                    ) as cursor:
                        name, new_stock = await cursor.fetchone()
                
                await interaction.followup.send(
                    f"Successfully added {stock_count} stock to {name}! New total stock: {new_stock}",
                    ephemeral=True
                )
                
                # Delete the message with the file
                try:
                    await message.delete()
                except:
                    pass
                    
            except TimeoutError:
                await interaction.followup.send("Timeout: No file was uploaded.", ephemeral=True)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Select a product to restock:", view=view, ephemeral=True)

    @app_commands.command(name="purchase", description="Purchase a product")
    async def purchase(self, interaction: discord.Interaction, quantity: int = 1, discount_code: str = None):
        if quantity < 1:
            await interaction.response.send_message("Quantity must be at least 1!", ephemeral=True)
            return

        # Initialize discount variables
        discount_amount = 0
        discount_type = None
        
        # Check discount code if provided
        if discount_code:
            async with aiosqlite.connect(self.bot.db_path) as db:
                async with db.execute('''
                    SELECT discount_amount, discount_type, uses_left
                    FROM discount_codes
                    WHERE code = ?
                    AND expiry_date > CURRENT_TIMESTAMP
                    AND uses_left > 0
                ''', (discount_code.upper(),)) as cursor:
                    discount = await cursor.fetchone()
                    
                    if not discount:
                        await interaction.response.send_message(
                            "Invalid or expired discount code!",
                            ephemeral=True
                        )
                        return
                    
                    discount_amount, discount_type, uses_left = discount

        async with aiosqlite.connect(self.bot.db_path) as db:
            # Check if user is blacklisted
            async with db.execute('SELECT is_blacklisted FROM users WHERE user_id = ?', 
                                (interaction.user.id,)) as cursor:
                result = await cursor.fetchone()
                if result and result[0]:
                    await interaction.response.send_message(
                        "You are blacklisted from using this bot.",
                        ephemeral=True
                    )
                    return

            # Get available products with stock
            async with db.execute(
                'SELECT id, name, price, stock FROM products ORDER BY name'
            ) as cursor:
                products = await cursor.fetchall()

        if not products:
            await interaction.response.send_message(
                "No products available for purchase!",
                ephemeral=True
            )
            return

        # Create selection menu for products with stock
        options = [
            discord.SelectOption(
                label=f"{name} ({price} credits)",
                description=f"Stock: {stock if stock is not None else 0}",
                value=str(id)
            ) for id, name, price, stock in products if (stock if stock is not None else 0) >= quantity
        ]

        if not options:
            await interaction.response.send_message(
                "No products have enough stock for your requested quantity!",
                ephemeral=True
            )
            return

        view = discord.ui.View()
        select = discord.ui.Select(
            placeholder="Choose a product to purchase",
            options=options
        )

        async def select_callback(interaction: discord.Interaction):
            product_id = int(select.values[0])
            
            async with aiosqlite.connect(self.bot.db_path) as db:
                # Get product details and check stock
                async with db.execute(
                    'SELECT name, price, stock FROM products WHERE id = ?',
                    (product_id,)
                ) as cursor:
                    product = await cursor.fetchone()
                    
                    if not product:
                        await interaction.response.send_message(
                            "Product not found!",
                            ephemeral=True
                        )
                        return
                    
                    name, price, stock = product
                    stock = stock if stock is not None else 0
                    
                    if stock < quantity:
                        await interaction.response.send_message(
                            f"Not enough stock! Available: {stock}",
                            ephemeral=True
                        )
                        return

                    # Calculate total cost with discount
                    total_cost = price * quantity
                    original_cost = total_cost
                    discount_saved = 0

                    if discount_amount and discount_type:
                        if discount_type == 'PERCENT':
                            discount_saved = int(total_cost * (discount_amount / 100))
                        else:  # FIXED
                            discount_saved = discount_amount
                        total_cost = max(0, total_cost - discount_saved)

                    # Check user's balance
                    async with db.execute(
                        'SELECT credits FROM users WHERE user_id = ?',
                        (interaction.user.id,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        balance = result[0] if result else 0

                    if balance < total_cost:
                        await interaction.response.send_message(
                            f"Insufficient credits! You need {total_cost} credits, but have {balance}.",
                            ephemeral=True
                        )
                        return

                    # Create confirmation message with discount info
                    confirm_message = f"Confirm purchase of {quantity}x {name}\n"
                    if discount_saved > 0:
                        confirm_message += f"Original cost: {original_cost} credits\n"
                        confirm_message += f"Discount: {discount_saved} credits\n"
                    confirm_message += f"Final cost: {total_cost} credits"

                    # Create confirmation button
                    confirm_view = discord.ui.View(timeout=30)  # 30 second timeout
                    
                    class ConfirmButton(discord.ui.Button):
                        def __init__(self):
                            super().__init__(
                                label="Confirm Purchase",
                                style=discord.ButtonStyle.green
                            )
                        
                        async def callback(self, interaction: discord.Interaction):
                            try:
                                # Defer the response since we'll be doing file operations
                                await interaction.response.defer(ephemeral=True)
                                
                                # Disable the button
                                self.disabled = True
                                try:
                                    await interaction.message.edit(view=self.view)
                                except:
                                    pass
                                
                                stock_file = f"products/stock_{product_id}.txt"
                                
                                # Get the lines from stock file but don't remove them yet
                                lines_to_send, remaining_lines = await self.view.cog.get_and_remove_lines(stock_file, quantity)
                                
                                if not lines_to_send:
                                    await interaction.followup.send(
                                        "Error: Could not retrieve stock. Please contact an administrator.",
                                        ephemeral=True
                                    )
                                    return
                                
                                # Generate purchase ID
                                purchase_id = await self.view.cog.generate_purchase_id()
                                
                                # Process the transaction FIRST
                                async with aiosqlite.connect(self.view.cog.bot.db_path) as db:
                                    try:
                                        # Process purchase
                                        await db.execute(
                                            'UPDATE users SET credits = credits - ? WHERE user_id = ?',
                                            (total_cost, interaction.user.id)
                                        )
                                        await db.execute(
                                            'UPDATE products SET stock = stock - ? WHERE id = ?',
                                            (quantity, product_id)
                                        )
                                        
                                        # Update discount code usage if used
                                        if discount_code:
                                            await db.execute('''
                                                UPDATE discount_codes 
                                                SET uses_left = uses_left - 1 
                                                WHERE code = ? AND uses_left > 0
                                            ''', (discount_code.upper(),))
                                        
                                        # Add transaction with discount info
                                        await db.execute('''
                                            INSERT INTO transactions 
                                            (purchase_id, user_id, product_id, amount, original_cost, discount_amount, discount_code) 
                                            VALUES (?, ?, ?, ?, ?, ?, ?)
                                        ''', (purchase_id, interaction.user.id, product_id, quantity, original_cost, discount_saved, discount_code))
                                        
                                        await db.commit()
                                        
                                        # Only after successful transaction, send the DM
                                        if quantity > 10:  # Threshold for sending as file
                                            stock_content = f"Purchase ID: {purchase_id}\n"
                                            stock_content += f"Product: {name} (Quantity: {quantity})\n\n"
                                            stock_content += "".join(lines_to_send)
                                            
                                            file = discord.File(
                                                io.StringIO(stock_content),
                                                filename=f"purchase_{purchase_id}.txt"
                                            )
                                            
                                            try:
                                                await interaction.user.send(
                                                    "Your purchase details are in the attached file:",
                                                    file=file
                                                )
                                            except Exception as e:
                                                # If DM fails, rollback the transaction
                                                await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                                                    (total_cost, interaction.user.id))
                                                await db.execute('UPDATE products SET stock = stock + ? WHERE id = ?',
                                                    (quantity, product_id))
                                                if discount_code:
                                                    await db.execute('UPDATE discount_codes SET uses_left = uses_left + 1 WHERE code = ?',
                                                        (discount_code.upper(),))
                                                await db.execute('DELETE FROM transactions WHERE purchase_id = ?', (purchase_id,))
                                                await db.commit()
                                                
                                                await interaction.followup.send(
                                                    "Error: Could not send DM. Please make sure your DMs are open and try again.",
                                                    ephemeral=True
                                                )
                                                return
                                        else:
                                            # For smaller quantities, send as regular message
                                            stock_message = f"Purchase ID: {purchase_id}\n"
                                            stock_message += f"Product: {name} (Quantity: {quantity})\n\n"
                                            stock_message += "```\n" + "".join(lines_to_send) + "```"
                                            stock_message += "\nKeep this Purchase ID for reference if you need support!"
                                            
                                            try:
                                                await interaction.user.send(stock_message)
                                            except Exception as e:
                                                # If DM fails, rollback the transaction
                                                await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                                                    (total_cost, interaction.user.id))
                                                await db.execute('UPDATE products SET stock = stock + ? WHERE id = ?',
                                                    (quantity, product_id))
                                                if discount_code:
                                                    await db.execute('UPDATE discount_codes SET uses_left = uses_left + 1 WHERE code = ?',
                                                        (discount_code.upper(),))
                                                await db.execute('DELETE FROM transactions WHERE purchase_id = ?', (purchase_id,))
                                                await db.commit()
                                                
                                                await interaction.followup.send(
                                                    "Error: Could not send DM. Please make sure your DMs are open and try again.",
                                                    ephemeral=True
                                                )
                                                return
                                        
                                        # Only remove the lines from stock file after successful DM
                                        if not await self.view.cog.remove_lines(stock_file, remaining_lines):
                                            # If removing lines fails, rollback everything
                                            await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                                                (total_cost, interaction.user.id))
                                            await db.execute('UPDATE products SET stock = stock + ? WHERE id = ?',
                                                (quantity, product_id))
                                            if discount_code:
                                                await db.execute('UPDATE discount_codes SET uses_left = uses_left + 1 WHERE code = ?',
                                                    (discount_code.upper(),))
                                            await db.execute('DELETE FROM transactions WHERE purchase_id = ?', (purchase_id,))
                                            await db.commit()
                                            
                                            await interaction.followup.send(
                                                "Error: Could not process purchase. Please try again.",
                                                ephemeral=True
                                            )
                                            return
                                        
                                        # Check if stock is now 0
                                        async with db.execute('SELECT stock FROM products WHERE id = ?', (product_id,)) as cursor:
                                            new_stock = (await cursor.fetchone())[0]
                                            if new_stock == 0:
                                                await self.view.cog.notify_stock_empty(name)
                                        
                                        # Create success message with discount info
                                        success_message = f"Purchase successful! {quantity}x {name}"
                                        if discount_saved > 0:
                                            success_message += f"\nOriginal cost: {original_cost} credits"
                                            success_message += f"\nDiscount applied: {discount_saved} credits"
                                        success_message += f"\nFinal cost: {total_cost} credits"
                                        success_message += f"\nPurchase ID: `{purchase_id}`"
                                        success_message += "\nStock has been sent to your DMs!"
                                        
                                        await interaction.followup.send(
                                            success_message,
                                            ephemeral=True
                                        )
                                    except Exception as e:
                                        print(f"Transaction error: {str(e)}")
                                        # Rollback everything if any error occurs
                                        await db.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                                            (total_cost, interaction.user.id))
                                        await db.execute('UPDATE products SET stock = stock + ? WHERE id = ?',
                                            (quantity, product_id))
                                        if discount_code:
                                            await db.execute('UPDATE discount_codes SET uses_left = uses_left + 1 WHERE code = ?',
                                                (discount_code.upper(),))
                                        await db.execute('DELETE FROM transactions WHERE purchase_id = ?', (purchase_id,))
                                        await db.commit()
                                        
                                        await interaction.followup.send(
                                            "Error: Could not process purchase. Please try again.",
                                            ephemeral=True
                                        )
                                        return
                            except Exception as e:
                                print(f"Error in purchase confirmation: {str(e)}")
                                await interaction.followup.send(
                                    "An error occurred during purchase confirmation. Please try again.",
                                    ephemeral=True
                                )
                                return
                    
                    # Add the button to the view
                    confirm_button = ConfirmButton()
                    confirm_view.add_item(confirm_button)
                    confirm_view.cog = self  # Store reference to cog for access in button callback
                    
                    # Add timeout handler
                    async def on_timeout():
                        for item in confirm_view.children:
                            item.disabled = True
                        try:
                            await interaction.edit_original_message(view=confirm_view)
                        except:
                            pass
                    
                    confirm_view.on_timeout = on_timeout
                    
                    await interaction.response.send_message(
                        confirm_message,
                        view=confirm_view,
                        ephemeral=True
                    )

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message(
            "Select a product to purchase:",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="manage_stock", description="[Admin] View and manage product stock")
    @app_commands.checks.has_role(ADMIN_ROLE_NAME)
    async def manage_stock(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.bot.db_path) as db:
            async with db.execute('SELECT id, name, stock FROM products ORDER BY name') as cursor:
                products = await cursor.fetchall()

        if not products:
            await interaction.response.send_message("No products available!", ephemeral=True)
            return

        # Create selection menu
        options = [
            discord.SelectOption(
                label=f"{name} (Stock: {stock if stock is not None else 0})",
                value=str(id)
            ) for id, name, stock in products
        ]
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Choose a product to manage stock", options=options)

        async def select_callback(interaction: discord.Interaction):
            product_id = int(select.values[0])
            stock_file = f"products/stock_{product_id}.txt"
            
            if not os.path.exists(stock_file):
                await interaction.response.send_message("No stock file found for this product!", ephemeral=True)
                return
            
            # Read all stock entries
            with open(stock_file, 'r', encoding='utf-8') as f:
                stock_lines = [line.strip() for line in f.readlines() if line.strip()]
            
            total_stock = len(stock_lines)
            if total_stock == 0:
                await interaction.response.send_message("No stock entries found!", ephemeral=True)
                return
            
            # Create pages of stock (10 entries per page)
            page_size = 10
            total_pages = math.ceil(total_stock / page_size)
            current_page = 0
            
            async def update_stock_message(page_num):
                start_idx = page_num * page_size
                end_idx = min(start_idx + page_size, total_stock)
                current_entries = stock_lines[start_idx:end_idx]
                
                # Format the stock entries with numbers
                formatted_entries = []
                for i, entry in enumerate(current_entries, start=start_idx + 1):
                    formatted_entries.append(f"{i}. {entry}")
                
                content = f"Stock entries (Page {page_num + 1}/{total_pages}):\n```\n"
                content += "\n".join(formatted_entries)
                content += "\n```\n\nTo remove specific entries, use `/remove_stock [product] [entry_numbers]`"
                return content
            
            # Create navigation buttons
            nav_view = discord.ui.View()
            
            prev_button = discord.ui.Button(
                label="Previous",
                style=discord.ButtonStyle.gray,
                disabled=True
            )
            next_button = discord.ui.Button(
                label="Next",
                style=discord.ButtonStyle.gray,
                disabled=total_pages <= 1
            )
            
            async def prev_callback(interaction: discord.Interaction):
                nonlocal current_page
                current_page = max(0, current_page - 1)
                prev_button.disabled = current_page == 0
                next_button.disabled = current_page >= total_pages - 1
                content = await update_stock_message(current_page)
                await interaction.response.edit_message(content=content, view=nav_view)
            
            async def next_callback(interaction: discord.Interaction):
                nonlocal current_page
                current_page = min(total_pages - 1, current_page + 1)
                prev_button.disabled = current_page == 0
                next_button.disabled = current_page >= total_pages - 1
                content = await update_stock_message(current_page)
                await interaction.response.edit_message(content=content, view=nav_view)
            
            prev_button.callback = prev_callback
            next_button.callback = next_callback
            
            nav_view.add_item(prev_button)
            nav_view.add_item(next_button)
            
            content = await update_stock_message(current_page)
            await interaction.response.send_message(content, view=nav_view, ephemeral=True)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Select a product to manage stock:", view=view, ephemeral=True)

    @app_commands.command(name="remove_stock", description="[Admin] Remove specific stock entries")
    @app_commands.checks.has_role(ADMIN_ROLE_NAME)
    async def remove_stock(self, interaction: discord.Interaction, product: str, entries: str):
        async with aiosqlite.connect(self.bot.db_path) as db:
            async with db.execute('SELECT id, name, stock FROM products WHERE name = ?', (product,)) as cursor:
                result = await cursor.fetchone()
                
                if not result:
                    await interaction.response.send_message("Product not found!", ephemeral=True)
                    return
                
                product_id, name, current_stock = result
                
        stock_file = f"products/stock_{product_id}.txt"
        if not os.path.exists(stock_file):
            await interaction.response.send_message("No stock file found for this product!", ephemeral=True)
            return
            
        # Parse entry numbers (format: "1,2,3" or "1-3" or "1,2,4-6")
        try:
            entry_numbers = set()
            for part in entries.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    entry_numbers.update(range(start, end + 1))
                else:
                    entry_numbers.add(int(part))
        except ValueError:
            await interaction.response.send_message(
                "Invalid entry format! Use numbers separated by commas or ranges (e.g., '1,2,3' or '1-3' or '1,2,4-6')",
                ephemeral=True
            )
            return
            
        # Read all stock entries
        with open(stock_file, 'r', encoding='utf-8') as f:
            stock_lines = [line.strip() for line in f.readlines() if line.strip()]
            
        # Validate entry numbers
        invalid_entries = [n for n in entry_numbers if n < 1 or n > len(stock_lines)]
        if invalid_entries:
            await interaction.response.send_message(
                f"Invalid entry numbers: {', '.join(map(str, invalid_entries))}",
                ephemeral=True
            )
            return
            
        # Remove the specified entries (convert to 0-based index)
        entries_to_remove = {n - 1 for n in entry_numbers}
        new_stock_lines = [line for i, line in enumerate(stock_lines) if i not in entries_to_remove]
        
        # Write back the remaining stock
        with open(stock_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_stock_lines) + '\n' if new_stock_lines else '')
            
        # Update the stock count in the database
        removed_count = len(stock_lines) - len(new_stock_lines)
        async with aiosqlite.connect(self.bot.db_path) as db:
            await db.execute(
                'UPDATE products SET stock = stock - ? WHERE id = ?',
                (removed_count, product_id)
            )
            await db.commit()
            
            # Check if stock is now 0
            async with db.execute('SELECT stock FROM products WHERE id = ?', (product_id,)) as cursor:
                new_stock = (await cursor.fetchone())[0]
                if new_stock == 0:
                    await self.notify_stock_empty(name)
            
        await interaction.response.send_message(
            f"Successfully removed {removed_count} stock entries from {name}!",
            ephemeral=True
        )

    async def generate_purchase_id(self):
        """Generate a unique purchase ID"""
        # Format: PUR-XXXXX where X is alphanumeric
        while True:
            purchase_id = 'PUR-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            
            # Check if ID already exists
            async with aiosqlite.connect(self.bot.db_path) as db:
                async with db.execute('SELECT 1 FROM transactions WHERE purchase_id = ?', (purchase_id,)) as cursor:
                    if not await cursor.fetchone():
                        return purchase_id

async def setup(bot):
    # Store config in bot instance for access
    bot.config = {}
    with open('config.json', 'r') as f:
        bot.config = json.load(f)
    
    # Add commands to all configured guilds
    cog = ProductManager(bot)
    await bot.add_cog(cog)
    
    # Sync commands for each guild
    for guild_id in bot.config['guild_ids']:
        guild = discord.Object(id=int(guild_id))
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        except Exception as e:
            print(f"Failed to sync commands in product manager for guild {guild_id}: {e}") 