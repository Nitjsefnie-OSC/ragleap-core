This folder holds your folder grants (grants.json). Only the sandbox runner reads it, mounted read-only.
Do not edit it by hand: use  ragleap files add | list | remove | off | on  instead.
It is not stored in git and is never copied into a Docker image.

Agent tools (off by default)
----------------------------
Set FILE_TOOLS_ENABLED=true (and SANDBOX_TOKEN) in .env and restart the app. AI employees then get
list_files and read_file for the grants you created. They can name a grant and a path inside it,
nothing else. After a list or a read, outgoing actions need approval.

Asking for access
-----------------
With FILE_TOOLS_ENABLED on, an AI employee can also use request_access to ask you for a folder.
It only suggests a grant name and a reason. The request always needs your approval, and approving
it grants nothing: you still run `ragleap files add /your/folder --name NAME` on the machine.
