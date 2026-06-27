This role of this file is to describe common mistakes and confusion points that agents might encounter as they work in this project. If you ever enounter something in the project that surprises you, please alert the developer working with you and indicate that this is the case in the AGENTS.md file to help prevent future agents from having the same issue. You can write your notes in the "Common Mistakes and Confusion Points" section below.

## General Guidelines for Agents
- If the current methods and functionalities are compatible with the new methods and functionalities that are to be added, try as much as possible not to change them. This is to prevent breaking the current code and to make debugging easier.

- ALWAYS assume the default terminal is PowerShell 7. If you run terminal-specific commands, make sure you always use commands compatible with PowerShell 7.

- By default (even if not in `/plan` mode), plan for the changes requested by the developer. after the planning is done and it is ready to implement, create an ENUMERATED .md file for that plan and save it in `.\plans` directory that exists in the current working directory and then STOP. The developer will then review the plan and give you the go-ahead to implement it. Do not implement the plan until the developer gives you the go-ahead.

- This is a Python project and so there is a virtual environment that is used to manage the dependencies. It is in the `.venv` folder. Always use the virtual environment in the project and do not search for the dependencies in your global environment. I assure you that the virtual environment is properly set up and working. You should not use global Python installations.

- To test the Python environment, first change your working directory to the project root and then either activate the virtual environment using `.\.venv\Scripts\activate` and run `python --version` or run `.venv\Scripts\python --version` to check the Python version. You should see Python 3.12.10.

- When you make changes to the bot, make sure to reflect those changes in the CHANGELOG.md file.

## Common Mistakes and Confusion Points
- When testing the project venv, call `.\.venv\Scripts\python.exe` directly from PowerShell 7. Do not wrap it in another `pwsh.exe -Command` invocation, because that extra layer can change quoting and startup behavior and make the venv look broken when it is not.