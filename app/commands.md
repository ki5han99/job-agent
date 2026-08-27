Yes. Here’s a clean **README-ready commands section** for the project so far.

````markdown
# Job Agent — Commands

## 1. Open the Project

```bash
cd ~/job-agent
````

If using VS Code from the terminal:

```bash
code .
```

---

## 2. Activate the Python Virtual Environment

```bash
source .venv/bin/activate
```

After activation, the terminal should show something like:

```text
(.venv) username@MacBook job-agent %
```

Verify Python:

```bash
which python
```

Expected path:

```text
~/job-agent/.venv/bin/python
```

Check Python version:

```bash
python --version
```

---

## 3. Deactivate the Virtual Environment

When finished working:

```bash
deactivate
```

---

# Ollama

## 4. Check Ollama Version

```bash
ollama --version
```

---

## 5. Start the Ollama Server

Run this in a separate terminal:

```bash
ollama serve
```

Leave this terminal running while the application is using Qwen.

The server should listen on:

```text
http://127.0.0.1:11434
```

---

## 6. Verify the Ollama Server

From another terminal:

```bash
curl http://localhost:11434/api/version
```

Expected response:

```json
{"version":"0.32.9"}
```

If you see:

```text
curl: (7) Failed to connect to localhost port 11434
```

the Ollama server is not running.

Start it with:

```bash
ollama serve
```

---

## 7. List Installed Models

```bash
ollama list
```

---

## 8. Check Models Currently Loaded in Memory

```bash
ollama ps
```

`ollama list` shows models installed on disk.

`ollama ps` shows models currently loaded/running.

---

## 9. Run Qwen Manually

```bash
ollama run qwen3.5:9b
```

This opens an interactive chat with the model.

Exit the model session with:

```text
Ctrl + D
```

or:

```text
/bye
```

---

## 10. Stop the Ollama Server

Go to the terminal running:

```bash
ollama serve
```

and press:

```text
Ctrl + C
```

---

# Python Environment

## 11. Create the Virtual Environment

This only needs to be done when setting up the project for the first time.

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

---

## 12. Upgrade pip

```bash
python -m pip install --upgrade pip
```

---

## 13. Install Python Dependencies

Current dependencies:

```bash
python -m pip install ollama pydantic PyYAML httpx
```

Current major packages used by the project:

```text
ollama
pydantic
PyYAML
httpx
```

Check installed packages:

```bash
python -m pip list
```

Check a specific package:

```bash
python -m pip show pydantic
```

For example:

```bash
python -m pip show ollama
python -m pip show PyYAML
```

---

# Running the Project

## 14. Run the Main Application

```bash
python main.py
```

This is currently the main development/testing entry point.

---

## 15. Test Python → Ollama → Qwen Communication

If `test_ollama.py` is still present:

```bash
python test_ollama.py
```

Expected output:

```text
PYTHON_CAN_TALK_TO_QWEN
```

This confirms:

```text
Python
  ↓
Ollama Python client
  ↓
Ollama server
  ↓
Qwen 3.5 9B
```

---

# Project Structure

## 16. Create the Base Project Directory

Initial setup:

```bash
mkdir -p ~/job-agent
cd ~/job-agent
```

---

## 17. Create Application Directories

```bash
mkdir -p app/llm
mkdir -p app/config
mkdir -p app/browser
mkdir -p app/database
mkdir -p app/jobs
mkdir -p data
mkdir -p tests
```

Or in one command:

```bash
mkdir -p app/{llm,config,browser,database,jobs} data tests
```

---

## 18. Create Python Package Files

```bash
touch app/__init__.py
touch app/llm/__init__.py
touch app/jobs/__init__.py
```

Additional package files can also be created with:

```bash
touch app/config/__init__.py
touch app/browser/__init__.py
touch app/database/__init__.py
```

---

## 19. Create Main Project Files

```bash
touch main.py
touch test_ollama.py
```

---

## 20. Create LLM Files

```bash
touch app/llm/client.py
```

---

## 21. Create Configuration Files

```bash
touch app/config/loader.py
touch app/config/models.py
```

---

## 22. Create YAML Data Files

```bash
touch data/profile.yaml
touch data/preferences.yaml
touch data/answers.yaml
```

These files have different responsibilities:

```text
profile.yaml
→ Candidate facts, experience, skills, education, projects

preferences.yaml
→ Which jobs should be considered or rejected

answers.yaml
→ Reusable application answers and later answer-engine configuration
```

---

## 23. Create Job Processing Files

```bash
touch app/jobs/models.py
touch app/jobs/filters.py
touch app/jobs/extractor.py
```

Current responsibilities:

```text
models.py
→ Job, ExtractedJobData, FilterResult

filters.py
→ deterministic job filtering

extractor.py
→ Qwen-based extraction from raw job descriptions
```

---

# Useful macOS / Terminal Commands

## 24. Show Current Directory

```bash
pwd
```

---

## 25. List Files

```bash
ls
```

More detail:

```bash
ls -la
```

---

## 26. Display Project Folder Structure

If `tree` is installed:

```bash
tree
```

Ignore `.venv`:

```bash
tree -I ".venv"
```

If `tree` is not installed:

```bash
brew install tree
```

---

## 27. Move Into a Directory

```bash
cd app
```

Go back one directory:

```bash
cd ..
```

Go to the project directly:

```bash
cd ~/job-agent
```

---

## 28. Create a Directory

```bash
mkdir directory_name
```

Create nested directories if necessary:

```bash
mkdir -p app/jobs
```

---

## 29. Create an Empty File

```bash
touch filename.py
```

Example:

```bash
touch app/jobs/extractor.py
```

---

## 30. Delete a File

```bash
rm filename
```

Be careful: this normally does not go to the macOS Trash.

---

## 31. Delete a Directory

For an empty directory:

```bash
rmdir directory_name
```

For a directory and its contents:

```bash
rm -rf directory_name
```

Use `rm -rf` carefully.

---

# Process Debugging

## 32. Check Ollama Processes

```bash
ps aux | grep -i ollama
```

This searches the active process list for anything containing `ollama`.

You may also see the `grep` command itself in the results. That is normal.

---

## 33. Find the Ollama Executable

```bash
which ollama
```

Expected on the current setup:

```text
/usr/local/bin/ollama
```

---

## 34. Find the Active Python Executable

```bash
which python
```

When `.venv` is active, this should point inside:

```text
~/job-agent/.venv/bin/python
```

---

## 35. Find pip Used by the Active Python

```bash
python -m pip --version
```

Using:

```bash
python -m pip
```

is preferred over simply:

```bash
pip
```

because it guarantees pip belongs to the currently active Python interpreter.

---

# YAML / Configuration Testing

## 36. Run Profile and Preferences Validation

Our Pydantic validation currently runs when the loaders are called from:

```bash
python main.py
```

For example:

```python
profile = load_profile()
preferences = load_preferences()
```

If the YAML schema is invalid, Pydantic raises a validation error.

If the YAML syntax itself is broken, PyYAML raises an error such as:

```text
yaml.scanner.ScannerError
```

---

# Daily Development Workflow

A typical development session uses two terminals.

### Terminal 1 — Ollama

```bash
cd ~/job-agent
ollama serve
```

Leave it running.

### Terminal 2 — Python Project

```bash
cd ~/job-agent
source .venv/bin/activate
curl http://localhost:11434/api/version
python main.py
```

When finished:

```bash
deactivate
```

Then switch to the Ollama terminal and press:

```text
Ctrl + C
```

---

# Quick Start

After the project has already been set up, the shortest startup procedure is:

```bash
cd ~/job-agent
source .venv/bin/activate
```

Start Ollama in another terminal:

```bash
ollama serve
```

Verify:

```bash
curl http://localhost:11434/api/version
```

Run the agent:

```bash
python main.py
```

Stop working:

```bash
deactivate
```

Then stop `ollama serve` with:

```text
Ctrl + C
```

````

One thing I’d add soon is a `requirements.txt` so setup becomes:

```bash
python -m pip install -r requirements.txt
````

instead of manually remembering `ollama`, `pydantic`, `PyYAML`, etc. We should also add `.gitignore` before putting this project into GitHub, especially because `profile.yaml` contains personal information.
