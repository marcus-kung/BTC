
# Bloomberg Trading Challenge (BTC)

## 1. Project Overview

This repository contains Python tools developed for the Bloomberg Trading Challenge 2026.

The project supports stock screening, market data collection, portfolio construction and risk analysis. It is designed to help our team evaluate a large universe of stocks, select a diversified portfolio and monitor its performance against the Bloomberg WLS Index.

**Main objectives:**
- Screen and rank stocks using financial and market data.
- Retrieve and enrich company information using Yahoo Finance.
- Analyse historical stock prices and returns.
- Construct and monitor a portfolio of approximately 10–12 stocks.
- Compare portfolio performance against the WLS benchmark.
- Analyse sector exposure, correlations and downside risk.

## 2. Repository Structure

```text
BTC/
├── data/                     # Input datasets (may be stored locally)
├── trading_dashboard/        # Portfolio monitoring and risk analysis
├── yahoo_enrichment/         # Company information and data enrichment
├── WLS Stock Screening .../  # Stock screening code and datasets
├── .gitignore                # Files excluded from Git tracking
└── README.md                 # Project documentation
```

Some folders may contain their own scripts, data files and dependencies.

## 3. Getting Started

### Step 1 — Install the required software

You will need:

- Python 3.10 or newer (subject to individual script requirements)
- Visual Studio Code (VS Code)
- Git
- A GitHub account

Useful links:

- Python: https://www.python.org/downloads/
- VS Code: https://code.visualstudio.com/
- Git: https://git-scm.com/downloads/
- GitHub: https://github.com/

### Step 2 — Clone the repository

Open VS Code and press:

**Mac:** `Cmd + Shift + P`  
**Windows:** `Ctrl + Shift + P`

Type `Git: Clone`, select it, and paste:

```bash
https://github.com/marcus-kung/BTC.git
```

Choose a folder where you want the project stored.

Once cloning finishes, select **Open**.

Alternatively, use the terminal:

```bash
git clone https://github.com/marcus-kung/BTC.git
cd BTC
code .
```

If `code .` is not configured, open the folder manually using **File → Open Folder** in VS Code.

**Important:** If you have already cloned the repository, open the existing folder rather than cloning another copy.

### Step 3 — Create a Python virtual environment

Open the VS Code terminal:

**Terminal → New Terminal**

Make sure the terminal is inside the `BTC` directory.

Create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
```

You should now see `(.venv)` at the beginning of your terminal prompt.

### Step 4 — Install Python dependencies

If the relevant project folder contains a `requirements.txt` file, install its dependencies.

For example:

```bash
python -m pip install -r yahoo_enrichment/requirements.txt
```

Repeat for other subprojects as necessary.

If a script reports a missing Python package, check its imports and the relevant requirements file.

### Step 5 — Select the Python interpreter

In VS Code:

1. Press `Cmd + Shift + P` (Mac) or `Ctrl + Shift + P` (Windows).
2. Select `Python: Select Interpreter`.
3. Choose the Python interpreter located inside `.venv`.

This ensures your scripts use the correct Python environment.

## 4. Using the Project

The repository is divided into several components.

### Stock Screening

The stock screening files are used to investigate the Bloomberg WLS stock universe and identify potential investments.

Typical workflow:

1. Obtain the relevant stock universe and ticker data.
2. Prepare the screening dataset.
3. Run the relevant screening scripts.
4. Review stock rankings and shortlisted candidates.
5. Share findings with the team.

### Yahoo Finance Enrichment

The `yahoo_enrichment/` directory contains tools for retrieving company information, including:

- Company names
- Tickers
- Sectors
- Industries

Some scripts read an existing Excel workbook, retrieve company metadata through `yfinance`, and write enriched results.

Check the individual script's required inputs and command-line arguments before running it.

### Trading Dashboard

The `trading_dashboard/` directory contains portfolio analysis tools.

Its intended functionality includes:

- Portfolio and benchmark returns
- Relative performance
- Stock and sector weights
- Correlations
- Return contributions
- Stress testing

Use the relevant input files and run the dashboard script according to its own configuration.

### Running Python Scripts

From the VS Code terminal, navigate to the appropriate folder:

```bash
cd yahoo_enrichment
```

Then run the relevant script:

```bash
python YOUR_SCRIPT_NAME.py
```

Replace `YOUR_SCRIPT_NAME.py` with the actual filename.

For scripts supporting command-line options, you can often inspect usage using:

```bash
python YOUR_SCRIPT_NAME.py --help
```

Return to the repository root using:

```bash
cd ..
```

## 5. Git and GitHub: Beginner's Guide

Git tracks changes to project files. GitHub stores the shared repository online so team members can collaborate.

### Key Terminology

| Term | Meaning |
|------|---------|
| Repository | A project folder tracked by Git |
| Clone | Download a GitHub repository onto your computer |
| Branch | A separate line of development |
| Commit | Save a snapshot of your changes locally |
| Push | Upload your commits to GitHub |
| Pull | Download and integrate changes from GitHub |
| Merge | Combine changes from different branches |
| Pull Request (PR) | Request to merge changes into another branch |
| `.gitignore` | Specifies files and folders Git should ignore |

### Check Your Git Status

Always open the terminal inside the repository folder.

```bash
git status
```

This displays your current branch and any changed or untracked files.

To check your branch:

```bash
git branch --show-current
```

To view available branches without opening the Git pager:

```bash
git --no-pager branch -a
```

### Download the Latest Changes

Before starting work, update your local `main` branch:

```bash
git switch main
git pull --ff-only origin main
```

If you have uncommitted changes, resolve or save them before switching branches or pulling.

### Recommended Workflow: Create Your Own Branch

When working collaboratively, avoid making all changes directly on `main`.

First, update `main`:

```bash
git switch main
git pull --ff-only origin main
```

Then create a branch for your task:

```bash
git switch -c feature/my-task
```

Replace `my-task` with a descriptive name, such as:

```bash
git switch -c feature/improve-dashboard
```

Make your changes in VS Code and save the files.

### Stage Your Changes

Check which files have changed:

```bash
git status
```

Stage a specific file:

```bash
git add path/to/file.py
```

Alternatively, stage all changes:

```bash
git add .
```

**Caution:** `git add .` stages all eligible files, so check that you are not accidentally including datasets, temporary files or secrets.

### Commit Your Changes

Save the staged changes as a Git commit:

```bash
git commit -m "Improve portfolio dashboard"
```

Use short, descriptive commit messages.

### Push Your Branch to GitHub

For a new feature branch:

```bash
git push -u origin feature/my-task
```

Replace `feature/my-task` with your branch name.

You can now see your branch on GitHub.

### Create a Pull Request

1. Open the BTC repository on GitHub.
2. Select **Compare & pull request** for your branch, or open the **Pull requests** tab.
3. Choose `main` as the target branch.
4. Describe your changes.
5. Submit the pull request.
6. Review and merge the changes after approval.

This allows teammates to inspect changes before they are added to the main project.

### Update Your Local Main Branch After a Merge

Once your pull request has been merged:

```bash
git switch main
git pull --ff-only origin main
```

Your local `main` will now contain the latest changes.

### Direct Pushes to Main

If you have permission and direct pushes are allowed:

```bash
git switch main
git pull --ff-only origin main
git add path/to/file.py
git commit -m "Update documentation"
git push origin main
```

For team collaboration, feature branches and pull requests are generally preferred.

## 6. Files That Should Not Be Uploaded

Avoid committing:

- Python virtual environments (`.venv/`)
- Python cache files (`__pycache__/`)
- macOS metadata files (`.DS_Store`)
- API keys and authentication credentials
- Large temporary datasets
- Generated output files that do not need version control

A basic `.gitignore` might contain:

```gitignore
.venv/
__pycache__/
*.pyc
.DS_Store
.env
```

The `data/` directory can also be ignored if its contents are intended to remain local.

**Note:** `.gitignore` does not automatically remove files that Git is already tracking.

## 7. Common Git Problems

### "Not a git repository"

You are probably using the terminal outside the cloned repository.

Check:

```bash
pwd
```

Navigate into the correct directory:

```bash
cd /path/to/BTC
```

Then run:

```bash
git status
```

### "No commits yet"

This usually means you initialised a new local repository instead of using the existing GitHub history.

Do not create an unrelated initial commit if the GitHub repository already contains commits.

Clone the existing repository or connect your local folder to the remote history carefully.

### Push Rejected

Your branch may be behind GitHub, or direct pushes to `main` may be restricted.

Check:

```bash
git status
git remote -v
```

If you're on `main` and have committed local changes, you may need to pull and resolve any conflicts before pushing.

If `main` is protected, use a feature branch and pull request.

### Merge Conflicts

A merge conflict occurs when Git cannot automatically combine competing changes.

Open the affected files in VS Code, review both versions, resolve the conflict, and complete the merge or rebase.

Do not force-push to `main` as a workaround.

## 8. Recommended Team Workflow

For every contribution:

1. **Pull** the latest version of `main`.
2. **Create** a branch for your task.
3. **Edit and test** your code locally.
4. **Commit** your changes with a descriptive message.
5. **Push** the branch to GitHub.
6. **Open a pull request** for review.
7. **Merge** once approved.
8. **Pull** the updated `main` branch before starting your next task.

For large datasets and shared deliverables, use the team's shared file storage where appropriate, keeping the GitHub repository focused on code, configuration and documentation.

---

## Repository

GitHub: https://github.com/marcus-kung/BTC

**Project:** Bloomberg Trading Challenge 2026  
**Language:** Python  
**Tools:** VS Code, Git, GitHub, Yahoo Finance, Excel

