# 🚀 Team Member Setup Guide (Non-Technical)

This guide is for team members who just want to **run the app** - no coding required!

---

## 📦 What You Need From Your Administrator

Ask your administrator to send you:
1. **The application folder** (ZIP file)
2. **The `.env` file** with API keys already configured

---

## 🖥️ Setup Instructions for Mac

### Step 1: Extract the ZIP File
1. Download the ZIP file your administrator sent you
2. Double-click to extract it
3. Move the extracted folder to your `Documents` or `Desktop`

### Step 2: Add the .env File
1. Your administrator will send you a file named `.env`
2. Place this `.env` file **inside** the application folder (same folder that has `start_app.sh`)

### Step 3: Run the Application
1. Open **Terminal** (search for "Terminal" in Spotlight)
2. Type `cd ` (with a space after cd) but **don't press Enter yet**
3. Drag the application folder from Finder into the Terminal window
4. Press **Enter**
5. Type: `./start_app.sh`
6. Press **Enter**

### Step 4: Use the Application
- The application will automatically start in your terminal
- After a few seconds, open your web browser and go to: **http://localhost:5001**
- You should see the AI Media Workflow Dashboard!

### To Stop the Application:
- Go back to the Terminal window
- Press `Ctrl + C`

---

## 🪟 Setup Instructions for Windows

### Step 1: Extract the ZIP File
1. Download the ZIP file your administrator sent you
2. Right-click the ZIP file and select "Extract All..."
3. Choose a location like `Documents` or `Desktop`

### Step 2: Add the .env File
1. Your administrator will send you a file named `.env`
2. Place this `.env` file **inside** the extracted application folder (same folder that has `start_app.bat`)

### Step 3: Run the Application
1. Open the application folder
2. Double-click the file named **`start_app.bat`**
3. A black window (Command Prompt) will open
4. Your web browser will automatically open to the application

### Step 4: Use the Application
- The application is now running!
- If the browser doesn't open automatically, go to: **http://localhost:5001**
- You should see the AI Media Workflow Dashboard!

### To Stop the Application:
- Go to the black Command Prompt window
- Press any key (or close the window)

---

## ⚠️ Troubleshooting

### "Virtual environment not found" Error
**Solution**: Your administrator needs to run the setup script first before packaging the folder for you.

**Administrator should run:**
- **Mac**: `./setup_auto.sh` then package the entire folder
- **Windows**: `setup_auto.bat` then package the entire folder

### ".env file not found" Error
**Solution**: Make sure the `.env` file is in the **main application folder**, not in a subfolder.

### "Port 5001 is already in use" Error
**Solution**: The application is already running! Close the previous window or restart your computer.

### Jobs Stay in "Queued" Status Forever
**Problem**: The background worker is not running.

**Solution**: 
1. Stop the application (Ctrl+C on Mac, or close window on Windows)
2. Run the startup script again: 
   - Mac: `./start_app.sh`
   - Windows: Double-click `start_app.bat`

The new startup scripts automatically start BOTH the web server and the worker!

### Application Won't Start
**Solution**: 
1. Make sure you're in the correct folder (the one with `start_app.sh` or `start_app.bat`)
2. Make sure you have the `.env` file in the folder
3. Contact your administrator for help

---

## 📞 Still Need Help?

Contact your administrator with:
1. A screenshot of the error message
2. What operating system you're using (Mac/Windows)
3. What step you're stuck on

---

## 🎯 Summary (Quick Reference)

### Mac:
```bash
cd /path/to/app/folder
./start_app.sh
# Open browser to: http://localhost:5001
# Press Ctrl+C to stop
```

### Windows:
1. Double-click `start_app.bat`
2. Browser opens automatically
3. Press any key in the Command Prompt to stop

**That's it!** 🎉
