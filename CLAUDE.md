This role of this file is to describe common mistakes and confusion points that agents might encounter as they work in this project. If you ever enounter something in the project that surprises you, please alert the developer working with you and indicate that this is the case in the CLAUDE.md file to help prevent future agents from having the same issue. You can write your notes in the "Common Mistakes and Confusion Points" section below.

## General Guidelines for Agents
- If the current methods and functionalities are compatible with the new methods and functionalities that are to be added, try as much as possible not to change them. This is to prevent breaking the current code and to make debugging easier.

- ALWAYS assume the default terminal is PowerShell 7. If you run terminal-specific commands, make sure you always use commands compatible with PowerShell 7.

- There is a Python 3.12 virtual environment in the project directory in `.venv` though it is ignored in `.gitignore`. Make sure to always use this environment.

- By default (even if not in `/plan` mode), plan for the changes requested by the developer. after the planning is done and it is ready to implement, create an ENUMERATED .md file for that plan and save it in `.\plans` directory that exists in the current working directory and then STOP. The developer will then review the plan and give you the go-ahead to implement it. Do not implement the plan until the developer gives you the go-ahead.

## Common Mistakes and Confusion Points