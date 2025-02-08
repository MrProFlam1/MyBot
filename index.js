const { Client, GatewayIntentBits, Collection, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const sqlite3 = require('sqlite3').verbose();
const dotenv = require('dotenv');
const fs = require('fs');
const path = require('path');

// Load environment variables
dotenv.config();

// Create bot client
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.GuildMembers,
        GatewayIntentBits.MessageContent
    ]
});

// Load config
const config = require('./config.json');

// Database setup
const db = new sqlite3.Database('credit_system.db');

// Initialize database tables
db.serialize(() => {
    // Users table
    db.run(`CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        credits INTEGER DEFAULT 0,
        is_blacklisted INTEGER DEFAULT 0
    )`);

    // Codes table
    db.run(`CREATE TABLE IF NOT EXISTS codes (
        code TEXT PRIMARY KEY,
        credits INTEGER,
        is_used INTEGER DEFAULT 0
    )`);

    // Products table
    db.run(`CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price INTEGER,
        file_path TEXT
    )`);

    // Transactions table
    db.run(`CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id TEXT UNIQUE,
        user_id TEXT,
        product_id INTEGER,
        amount INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )`);
});

// Command collection
client.commands = new Collection();

// Ready event
client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}`);
    console.log('Connected to guilds:');
    client.guilds.cache.forEach(guild => {
        console.log(`- ${guild.name} (ID: ${guild.id})`);
    });
    
    // Register slash commands for each guild
    const commands = [
        {
            name: 'balance',
            description: 'Check your credit balance'
        },
        {
            name: 'add_credits',
            description: '[Admin] Add credits to a user',
            options: [
                {
                    name: 'user',
                    type: 6, // USER type
                    description: 'The user to add credits to',
                    required: true
                },
                {
                    name: 'amount',
                    type: 4, // INTEGER type
                    description: 'Amount of credits to add',
                    required: true
                }
            ]
        },
        {
            name: 'redeem',
            description: 'Redeem a code for credits',
            options: [
                {
                    name: 'code',
                    type: 3, // STRING type
                    description: 'The code to redeem',
                    required: true
                }
            ]
        },
        {
            name: 'blacklist',
            description: '[Admin] Blacklist a user',
            options: [
                {
                    name: 'user',
                    type: 6, // USER type
                    description: 'The user to blacklist',
                    required: true
                }
            ]
        }
    ];

    config.guild_ids.forEach(async guildId => {
        try {
            const guild = await client.guilds.fetch(guildId);
            await guild.commands.set(commands);
            console.log(`Registered commands for guild ${guildId}`);
        } catch (error) {
            console.error(`Error registering commands for guild ${guildId}:`, error);
        }
    });
});

// Interaction handler
client.on('interactionCreate', async interaction => {
    if (!interaction.isCommand()) return;

    const { commandName } = interaction;

    // Check for blacklist
    if (commandName !== 'balance') {
        const blacklistCheck = await new Promise((resolve, reject) => {
            db.get('SELECT is_blacklisted FROM users WHERE user_id = ?', 
                [interaction.user.id], 
                (err, row) => {
                    if (err) reject(err);
                    resolve(row?.is_blacklisted === 1);
                });
        });

        if (blacklistCheck) {
            return interaction.reply({
                content: 'You are blacklisted from using this bot.',
                ephemeral: true
            });
        }
    }

    try {
        switch (commandName) {
            case 'balance':
                db.get('SELECT credits FROM users WHERE user_id = ?', 
                    [interaction.user.id], 
                    async (err, row) => {
                        if (err) throw err;
                        const credits = row ? row.credits : 0;
                        await interaction.reply({
                            content: `Your balance: ${credits} credits`,
                            ephemeral: true
                        });
                    });
                break;

            case 'add_credits':
                // Check for admin role
                if (!interaction.member.roles.cache.some(role => role.name === "Admin")) {
                    return interaction.reply({
                        content: "You need the 'Admin' role to use this command.",
                        ephemeral: true
                    });
                }

                const user = interaction.options.getUser('user');
                const amount = interaction.options.getInteger('amount');

                db.run('INSERT OR IGNORE INTO users (user_id, credits) VALUES (?, 0)',
                    [user.id], (err) => {
                        if (err) throw err;
                        db.run('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                            [amount, user.id], async (err) => {
                                if (err) throw err;
                                await interaction.reply({
                                    content: `Added ${amount} credits to ${user.toString()}'s account!`,
                                    ephemeral: true
                                });
                            });
                    });
                break;

            case 'redeem':
                const code = interaction.options.getString('code');
                db.get('SELECT credits FROM codes WHERE code = ? AND is_used = 0',
                    [code], async (err, row) => {
                        if (err) throw err;
                        if (!row) {
                            return interaction.reply({
                                content: 'Invalid or already used code!',
                                ephemeral: true
                            });
                        }

                        const credits = row.credits;
                        db.run('UPDATE codes SET is_used = 1 WHERE code = ?', [code]);
                        db.run('INSERT OR IGNORE INTO users (user_id, credits) VALUES (?, 0)',
                            [interaction.user.id]);
                        db.run('UPDATE users SET credits = credits + ? WHERE user_id = ?',
                            [credits, interaction.user.id]);

                        await interaction.reply({
                            content: `Successfully redeemed ${credits} credits!`,
                            ephemeral: true
                        });
                    });
                break;

            case 'blacklist':
                // Check for admin role
                if (!interaction.member.roles.cache.some(role => role.name === "Admin")) {
                    return interaction.reply({
                        content: "You need the 'Admin' role to use this command.",
                        ephemeral: true
                    });
                }

                const targetUser = interaction.options.getUser('user');
                db.run('INSERT OR REPLACE INTO users (user_id, is_blacklisted) VALUES (?, 1)',
                    [targetUser.id], async (err) => {
                        if (err) throw err;
                        await interaction.reply({
                            content: `${targetUser.toString()} has been blacklisted.`,
                            ephemeral: true
                        });
                    });
                break;
        }
    } catch (error) {
        console.error(error);
        await interaction.reply({
            content: 'An error occurred while executing this command.',
            ephemeral: true
        });
    }
});

// Error handling
client.on('error', error => {
    console.error('Discord client error:', error);
});

process.on('unhandledRejection', error => {
    console.error('Unhandled promise rejection:', error);
});

// Login
client.login(process.env.TOKEN); 