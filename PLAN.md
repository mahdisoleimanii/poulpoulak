I have in mind to create a Telegram bot to simplify group expenses. Basically it is used in group chats where people go out together and share expenses, like for meals, trips, or events. The bot will help track who paid for what, how much each person owes, and will provide a summary of the expenses at the end. It will also simplify the process of settling debts and so reducing the number of total transactions. Here are the features I have in mind:
1) It should only work when added to a group chat. It will be useless to a single user who starts the bot.
2) I intend to share the source code publicly on GitHub so everyone can have their own instance. This means that each instance (denoted by its bot token) will have its own data. The most important thing from the get-go is that there will be an environment variable SUPER_ADMINS which will contain a list of user IDs.
3) When someone other than SUPER_ADMINS starts the bot, it should only display a message giving general information about the bot and the original repo link.
4) When someone from the SUPER_ADMINS list starts the bot, it should display a welcome message and instructions on how to use the bot. 
5) To use the bot, it should be added to a group chat and if it is added by someone other than SUPER_ADMINS, it should display an error message indicating that only SUPER_ADMINS can add the bot to a group chat, and therefore the bot will not function in that group.
6) The interface of the bot is Persian by default and will only support Persian for now.
7) The bot is invoked when someone in the group chat (doesn't matter if they are one of the SUPER_ADMINS or not. The important thing about SUPER_ADMINS is that they are the only ones who can add the bot to a group chat) sends a message containing only the keyword "دنگ" and nothing else.
8) When two people send the keyword, the bot will only answer the one that sent it sooner as to prevent conflict.
9) When the keyword is sent, the bot will respond with this message:
"""
سلام @[username]!

امیدوارم که بهتون خوش گذشته باشه 😁!
بریم خرجا رو حساب کنیم. اگه بیشتر از یه نفر هم حساب کرده نگران نباش، بعدش درستش میکنیم.

کی پول داده؟
"""

Here the bot will show a list of inlinebuttons with the username of every group member in the chat. Do not include the bot itself or other bots in this list. The user who sent the keyword will select the person who paid first. There should also be an option for "None of the above" in case the payer is not listed. If "None of the above" is selected, the bot will ask for the name of the payer to be entered manually. At the end of this list of inlinebuttons there should a button "بیخیال ❌" which will cancel the process and send a message saying "هیچ خرجی ثبت نشد."

10) After the payer is selected, the bot will ask this:
"""
@[username] چقد پول داد؟ (به تومن وارد کن)
"""

Here the bot will wait for the user to input the amount paid. The input should be validated to ensure it is a positive number. If the input is invalid, the bot will prompt the user to enter a valid amount. The payment value might be a very large number or even contain decimal points, so the bot should handle such cases appropriately. The should be two inlinebuttons here: 1) "تغییر پرداخت کننده" which will take the user back to the previous step to select a different payer, and 2) "بیخیال ❌" which will cancel the process and send a message saying "هیچ خرجی ثبت نشد."

11) After the amount is entered, the bot will ask this:
"""
این خرج مال کیاست؟
"""

Here the bot will again show a list of inlinebuttons with the username of every group member in the chat, allowing multiple selections. Do not include the bot itself or other bots in this list. The user can select all the members who are sharing this expense. There should also be an option for "None of the above" in case some members are not listed. If "None of the above" is selected, the bot will ask for the names of the members to be entered manually. The inlinebuttons will use these two emojis next to usernames to display which ones are selected: "🔘" for not selected and "🟢" for selected. At the end of this list of inlinebuttons there should be two buttons: 1) "تغییر مبلغ" which will take the user back to the previous step to change the amount, and 2) "بیخیال ❌" which will cancel the process and send a message saying "هیچ خرجی ثبت نشد."

12) After the members are selected, the bot asks this:
"""
کس دیگه ای هم خرج کرده؟

اگه آره، انتخابش کن. اگه نه، بزن "✅ تموم"
"""

Here the bot will show a button "✅ تموم" alongside the list of usernames, similar to part 9.

13) If there is more than one person who paid, the bot will repeat the previous process.
14) Through this process the bot will only accept inputs when the message is replied on to the question that the bot asked so the conversation in the group is not interrupted and it will reply back to the response (using the Telegram's reply functionality) and it will only accept inputs from the user that first sent the keyword

15) To split the bills, the bot must obey this: The people that owe must never make more than ONE TRANSACTION. Here is how it works:
a. When the expenses were paid by 1 person it is a simple division.
b. When there are multiple people that paid, more than 1 person may end up being owed. I'll clarify by an example

Example for 15: A, B, C, D and E were out. A paid 500 for B, C, D and E (A himself wasn't included here). Later B paid 450 for everyone (B himself included). In this equation:
A is owed 410 - B is owed 235 - C, D and E each owe 215.
Here each 215 <= 410 and 215 <= 235. But since 215 doesn't divide neither 235 or 215, here is what we do. So one of C, D or E will pay their debt to B. Now B is owed 20. The other two will pay A their amount, 215. Now A pays B 20.

Another example for 15: A, B, C, D and E were out. A paid 400 for everyone (A himself included). Later B paid 600 for everyone (B himself included). In this equation:
A is owed 200 - B is owed 400 - C, D and E each owe 200.
Here, the split is simple. One of C, D or E pays A. Then the other two pay B.

NOTE: If you still had confusions after reading part 15 about how to split MAKE SURE TO ASK. 

16) After the process is done the bot sends a message tagging the people who owe and are owed, by their username telling them how much to pay whom. Here is a sample:
@[username1]
به: @[username_dest1]
مبلغ: x تومن

@[username2]
به: @[username_dest2] or maybe @[username_dest1]
مبلغ: x تومن

17) If someone sends the keyword and doesn't use it for 5 minutes, the bot must deactivate the menu that it sent.
18) While someone is using the bot by sending the keyword, no one else should be able to use the bot.
19) I want this project to be dockerized in the most efficient container. And so this is why the programming language selection is important.
20) I have created a Python 3.12 virtual environment just in case we decided to use Python. If another programming language was selected, ignore the `.venv` directory entirely.
20) I don't want the bot to hold any data at all.
21) The bot should have a .github/workflows/deploy.yml file so that it can be easily deployed into a VPS.

NOTE: If you think there are more problems that need addressing, tell me before going forward.