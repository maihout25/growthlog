# Host GrowthLog for free from GitHub

Keep the code in `maihout25/growthlog` on GitHub. PythonAnywhere runs Flask and
stores your SQLite database. You do not need to buy a domain or hosting plan.

The free Beginner plan currently includes one web app, one web worker, and
512 MiB of file storage. Its website expires after one month unless you extend
the expiry from the dashboard. Check that date regularly. There are no scheduled
tasks for new free accounts. These limits were checked on 1 October 2026 in
[PythonAnywhere's free-plan documentation](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/).
[SQLite is supported](https://help.pythonanywhere.com/pages/KindsOfDatabases).

These instructions start with a fresh online journal. Your PC's journal and
passwords are not uploaded or synchronized by Git. See the transfer section
before creating an online account if you want your existing records instead.

## 1. Create your free hosting account

Use [PythonAnywhere's Beginner registration](https://www.pythonanywhere.com/registration/register/beginner/).
Choose the free Beginner account. Your address will be
`https://YOUR_USERNAME.pythonanywhere.com`. This guide uses the US service at
`www.pythonanywhere.com`; EU accounts use a different website suffix.

Keep your PythonAnywhere password private. Your hosting account manages the
server; your GrowthLog account signs in to the journal. They are separate.

## 2. Get the code from GitHub

First, make sure the hosting-preparation commit is pushed to GitHub. It includes
`administration.py`, `login_throttle.py`, and `deploy/pythonanywhere_wsgi.py`.

Your repository is private. In GitHub's **Settings > Developer settings >
Personal access tokens > Fine-grained tokens**, create a token with an expiry,
resource owner `maihout25`, access to **only** the `growthlog` repository, and
repository **Contents: Read-only** permission. Other permissions can remain at
their defaults. Keep the token private and use it only at Git's password prompt.
[GitHub explains these token settings here](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

Open **Consoles > Bash** in PythonAnywhere and run:

```bash
git -c credential.helper= clone https://github.com/maihout25/growthlog.git ~/growthlog
cd ~/growthlog
```

If prompted, the GitHub username is `maihout25`; the password is your read-only
token, not your GitHub account password. Do not put the token inside a command
or repository URL. The empty `credential.helper` prevents Git from saving it.
An expired token affects future pulls, not the already-running website.
[PythonAnywhere supports pulling GitHub repositories over HTTPS](https://help.pythonanywhere.com/pages/ExternalVCS/).

`git clone` downloads the code and its version history. `cd` enters that folder.

## 3. Install the dependencies and create your GrowthLog account

In the same PythonAnywhere Bash console:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
.venv/bin/python -m flask --app app create-user
```

Use a Python version available in the Web tab (3.13 is used here). The virtual
environment and the web app must use the **same Python version**. Python 3.9 or
newer is required by the current Flask dependency; 3.13 is a suitable choice.

The first command creates an isolated Python environment. The second installs
the packages listed in `requirements.txt`; avoiding the download cache saves
space on the free account. The third prompts for a GrowthLog username and a
password twice, with password input hidden. Choose at least 10 characters.

Run `create-user` only when you want another account. It never replaces an
existing account. Your existing PC account will work online only if you transfer
its database, as described below.

## 4. Configure the website

Open **Web > Add a new web app**. Choose the free PythonAnywhere address, then
**Manual configuration**, then **Python 3.13** (matching the environment above).

Set these Web-tab values, replacing `YOUR_USERNAME` with your hosting username:

| Setting | Value |
| --- | --- |
| Source code | `/home/YOUR_USERNAME/growthlog` |
| Working directory | `/home/YOUR_USERNAME/growthlog` |
| Virtualenv | `/home/YOUR_USERNAME/growthlog/.venv` |
| Static files URL | `/static/` |
| Static files directory | `/home/YOUR_USERNAME/growthlog/static` |

Open the **WSGI configuration file** using its link on the Web tab. Replace the
sample contents with the contents of `deploy/pythonanywhere_wsgi.py` from your
repository, and save. That small file finds the project in your home directory,
enables production settings, and gives PythonAnywhere the Flask application.
For an EU account, change its hostname suffix to `eu.pythonanywhere.com`.

Turn on **Force HTTPS** in the Web tab, then click **Reload**. This ensures login
cookies travel over HTTPS. You do not run the Flask development server or keep
a console open for the website to run.
[Flask setup instructions](https://help.pythonanywhere.com/pages/Flask/)
and [Force HTTPS instructions](https://help.pythonanywhere.com/pages/ForcingHTTPS/).

## 5. Verify the live website

Open your HTTPS website address and sign in with the GrowthLog account you
created in step 3. Check these once after deployment:

1. Record an activity with a reflection and confirm it appears in the journal.
2. Reload the web app from PythonAnywhere's Web tab, then check the saved entry
   still exists. The `instance` folder persists separately from Git changes.
3. Edit and delete that test activity and check the weekly count changes.
4. Open the address in a private browser window and check that it requires login.
5. Check the layout on your phone and note the free website's expiry date.

Public registration is closed in hosted mode. `/setup` and `/register` return a
closed-registration message, including before the first account exists. To add
someone you trust, use the private `create-user` console command again.

## Update the website from GitHub

After committing and pushing code from VS Code or Codespaces, open your
PythonAnywhere Bash console and run these commands one at a time. Stop if a
command fails:

```bash
cd ~/growthlog
.venv/bin/python -m flask --app app backup-db
git -c credential.helper= pull --ff-only origin main
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
```

Supply your GitHub read-only token at the password prompt if asked. Then click
**Reload** on the Web tab. `--ff-only` makes Git stop if server-side code edits
conflict with the repository, so they are not silently replaced. If the WSGI
template changes, copy its new contents into the Web-tab WSGI file too.

Pushing code to GitHub does not automatically reload this free setup. Code
updates do not overwrite the ignored `instance` folder or its saved records.

## Backups and transferring an existing journal

On PythonAnywhere, run:

```bash
cd ~/growthlog
.venv/bin/python -m flask --app app backup-db
```

This uses SQLite's backup API to create a consistent copy in
`instance/backups/`, even while the app is running. Download that copy from the
Files tab and keep it privately outside the hosting account. A backup on the
same host alone does not protect against losing the hosting account. Keep an
eye on storage space as backups accumulate; new free plans have no scheduled
task feature, so backups here are manual.

To start with your PC's existing journal, **before creating any online records**:

1. On your PC, run
   `.\.venv\Scripts\python.exe -m flask --app app backup-db`.
2. Upload that backup privately through PythonAnywhere's Files tab as
   `/home/YOUR_USERNAME/growthlog/instance/growthlog.sqlite3`. Create the
   `instance` directory first if needed. The website should not be enabled yet.
3. Skip `create-user` and sign in using your existing GrowthLog credentials.
   Keep the host's generated session key; your local browser sessions need not
   transfer.

Do not upload the SQLite file, session key, passwords, or tokens to GitHub.
An existing online database should be backed up before any restore and the
website disabled while replacing it; restoration replaces records rather than
merging them. Stop local use of the old copy if you intend the hosted journal to
be your main journal, because the two databases do not synchronize.

## What the hosting settings do

- `GROWTHLOG_ENV=production` closes browser registration, disables debugging,
  and enables HTTPS-only cookies. Normal local commands keep local defaults.
- `GROWTHLOG_TRUSTED_HOSTS` allows only your configured website hostname.
- `GROWTHLOG_DATA_DIR` chooses where the database and generated session key live.
  The PythonAnywhere template uses the persistent `growthlog/instance` folder.
- The sign-in throttle allows eight attempts per username in 15 minutes and
  30 attempts overall per minute. It is held in memory for the free plan's one
  web worker and resets on reload. Use a shared rate-limit store if you later
  move to multiple workers or a larger public service.
- Reminders still require GrowthLog to be open in your browser. Hosting does
  not add email or background push notifications.

If you see an error page, use the **error log** link in the Web tab. Check the
Python version, virtualenv path, and WSGI file first. If the hostname is rejected,
check `GROWTHLOG_TRUSTED_HOSTS` in the WSGI file against your actual web address.
