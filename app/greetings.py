"""VERONICA's spoken 'Hello Boss' lines for admin sign-in.

They are recorded ONCE in her own voice (python -m tools.manage boss-voice  /  MAKE_BOSS_VOICE.bat) and kept as
app/static/boss/hello_<n>.mp3, so a sign-in never spends the daily voice quota and always plays instantly.
"""
BOSS_LINES = [
    "Hello Boss! How are you? Is everything good? I hope the coffee is strong and the scrap numbers are weak. How can I help you today?",
    "Hello Boss! Welcome back. How are you? Is everything good? I kept the data warm and the reports on their best behaviour. How can I help you today?",
    "Hello Boss! How are you? Is everything good? All systems are online, the ERP is synced, and I am only slightly smarter than yesterday. How can I help you today?",
    "Hello Boss! How are you? Is everything good? Production is rolling, I am running on pure electricity, and ready to crunch numbers. How can I help you today?",
]
