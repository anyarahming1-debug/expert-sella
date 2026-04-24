# 📋 Deployment Guide: Profit Analyzer

## Complete Step-by-Step Setup

---

## PART 1: GitHub Setup (3 minutes)

### 1.1: Create GitHub Account (skip if you have one)
- Go to **https://github.com**
- Click "Sign up"
- Verify email

### 1.2: Create New Repository
1. Go to **https://github.com/new**
2. Fill in:
   - **Repository name:** `profit-analyzer`
   - **Description:** "Real-time profit calculator"
   - **Public:** ✓ Check this box (IMPORTANT!)
   - **Add a README file:** ✓ Check this
3. Click **"Create repository"**

### 1.3: Upload Your Files
1. Open your repo (you should be on it)
2. Click **"Add file"** dropdown → **"Upload files"**
3. Drag & drop these 4 files:
   - `profit_analyzer.py`
   - `requirements.txt`
   - `.gitignore`
   - `sample_products.csv`
4. Click **"Commit changes"** button at bottom

**✓ GitHub is done!**

---

## PART 2: Streamlit Cloud Deployment (5 minutes)

### 2.1: Create Streamlit Account
1. Go to **https://streamlit.io/cloud**
2. Click **"Sign in"**
3. Click **"Sign in with GitHub"**
4. Authorize Streamlit to access your GitHub
5. Done!

### 2.2: Deploy Your App
1. You should see **"New app"** button
2. Click **"New app"**
3. Fill in:
   - **Repository:** `YOUR_USERNAME/profit-analyzer`
   - **Branch:** `main`
   - **Main file path:** `profit_analyzer.py`
4. Click **"Deploy"**

### 2.3: Wait for Deployment
- Streamlit will show a spinning loader
- This takes 30-60 seconds
- You'll see "Building..." then "Running"

### 2.4: Get Your URL
Once it says "Running", Streamlit shows your app URL:
```
https://profit-analyzer.streamlit.app
```

**Copy this URL and share with your VAs!**

---

## How Your VAs Use It

They just:
1. **Open the URL** in browser
2. **Upload CSV** or **paste product titles**
3. **Click "Start Analysis"**
4. **Download Excel** when done

That's it. No installation, no coding, no confusion.

---

## Making Changes Later

If you need to update the app:

### Option A: Edit on GitHub Website
1. Go to your repo
2. Click `profit_analyzer.py`
3. Click pencil icon (edit)
4. Make changes
5. Click "Commit changes"
6. Streamlit auto-deploys in ~30 sec

### Option B: Edit Locally & Push
```bash
# In your terminal:
git clone https://github.com/YOUR_USERNAME/profit-analyzer.git
cd profit-analyzer

# Edit profit_analyzer.py in your code editor

git add .
git commit -m "Updated shipping costs"
git push
```

Streamlit detects the push and re-deploys automatically.

---

## Common Issues & Fixes

### "Repository not found"
**Problem:** Streamlit can't see your repo  
**Fix:** Make sure repo is PUBLIC (not private)
- Go to repo → Settings → Change visibility to Public

### "Module not found error"
**Problem:** App missing dependencies  
**Fix:** Make sure `requirements.txt` is in root folder (not in a subfolder)

### "Can't connect to GitHub"
**Problem:** Authorization failed  
**Fix:** 
- Log out of Streamlit
- Log back in
- Authorize again with GitHub

### "App loads but crashes"
**Problem:** Python error in app  
**Fix:**
- Click "Manage app" button (top right)
- Click "Reboot app"
- Check the logs for error messages

### "Slow performance"
**Problem:** Takes too long per product  
**Fix:**
- eBay is rate-limiting
- Run smaller batches (100-500 items)
- Run during off-hours

---

## File Checklist

Before deploying, make sure you have:
- ✓ `profit_analyzer.py`
- ✓ `requirements.txt`
- ✓ `.gitignore`
- ✓ `sample_products.csv`

All 4 files should be in the root folder of your GitHub repo (not in subfolders).

---

## Testing Locally (Optional)

Want to test before deploying?

```bash
# Install dependencies
pip install -r requirements.txt

# Run app locally
streamlit run profit_analyzer.py

# Opens at http://localhost:8501
```

---

## Support

**Streamlit Help:** https://docs.streamlit.io  
**GitHub Help:** https://docs.github.com  
**eBay API Info:** https://developer.ebay.com  

---

**Done! Share your Streamlit URL with VAs and they can start analyzing immediately. 🎉**
