# Discord Credit Bot

A Discord bot with a credit system that allows users to purchase products using credits. The bot includes features for managing credits, products, and user permissions.

## Features

- Credit system with user balances
- Redeemable code generation
- Product management system
- Role-based permissions (Admin and Customer)
- Purchase system with confirmation
- Blacklist system
- Transaction history

## Setup Instructions

1. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a new Discord application and bot at https://discord.com/developers/applications

3. Configure the bot:
   - Copy your bot token
   - Edit `config.json` and replace `YOUR_DISCORD_BOT_TOKEN_HERE` with your bot token
   - Replace `YOUR_GUILD_ID_HERE` with your Discord server ID

4. Set up Discord roles:
   - Create two roles in your Discord server:
     - "CreditBot Admin" - For administrators
     - "CreditBot Customer" - For regular users

5. Run the bot:
   ```bash
   python credit_bot.py
   ```

## Commands

### Admin Commands
- `/add_credits <user> <amount>` - Add credits to a user's account
- `/generate_code <credits>` - Generate a redeemable code
- `/blacklist <user>` - Blacklist a user from using the bot
- `/add_product <name> <price>` - Add a new product (attach file)
- `/remove_product <product_id>` - Remove a product
- `/list_products` - List all available products

### User Commands
- `/balance` - Check your credit balance
- `/redeem <code>` - Redeem a code for credits
- `/purchase <quantity>` - Purchase a product

## File Structure
```
├── credit_bot.py        # Main bot file
├── product_manager.py   # Product management commands
├── config.json          # Bot configuration
├── requirements.txt     # Python dependencies
└── products/           # Directory for product files
```

## Database Structure

The bot uses SQLite for data storage with the following tables:
- users: Stores user credits and blacklist status
- codes: Stores redeemable codes
- products: Stores product information
- transactions: Stores purchase history

## Security Notes

- Keep your bot token secret
- Regularly backup the database
- Only give the Admin role to trusted users
- Monitor the transaction history for suspicious activity 