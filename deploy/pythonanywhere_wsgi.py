"""Copy this file into the WSGI configuration linked on PythonAnywhere's Web tab."""

import os
import sys
from pathlib import Path

# Clone the repository into /home/YOUR_USERNAME/growthlog.
project_directory = Path.home() / "growthlog"
sys.path.insert(0, str(project_directory))

os.environ["GROWTHLOG_ENV"] = "production"
# For an EU account, change pythonanywhere.com to eu.pythonanywhere.com.
os.environ["GROWTHLOG_TRUSTED_HOSTS"] = f"{Path.home().name}.pythonanywhere.com"
os.environ["GROWTHLOG_DATA_DIR"] = str(project_directory / "instance")

# PythonAnywhere's web server looks for a WSGI callable named application.
from app import app as application
