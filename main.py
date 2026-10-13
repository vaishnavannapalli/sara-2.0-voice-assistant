import json
import os
import re
import time
import sys
import json as _json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import pyttsx3
import speech_recognition as sr

# =========================================================
# SARA 2.0 — COMMANDS 1 TO 7
# Voice shifts, identity/wake-up, conversation/greetings, automatic memory, nicknames
# =========================================================

VOICE_RATE = 165
MEMORY_FILE = Path(__file__).resolve().parent / "sara_memory.json"

print("Starting Sara 2.0...")

# Find installed female voices (Microsoft Zira / Hazel)
engine = pyttsx3.init("sapi5")
installed_voices = engine.getProperty("voices")
female_voices = {}
for voice in installed_voices:
    voice_name = voice.name.lower()
    if "zira" in voice_name:
        female_voices["zira"] = voice.id
    elif "hazel" in voice_name:
        female_voices["hazel"] = voice.id
engine.stop()
del engine

if not female_voices:
    print("No supported female voice found. Check Windows speech settings.")
    input("Press Enter to close...")
    raise SystemExit

current_voice = "zira" if "zira" in female_voices else "hazel"

# Command 15 keeps the original transcript so non-English song titles are not lost.
LAST_RAW_TRANSCRIPT = ""
MUSIC_RECOGNIZER = None
MUSIC_MICROPHONE = None


def speak(message):
    """Speak and print a response using the selected Windows voice."""
    global current_voice
    message = str(message)
    print("Sara:", message)
    engine = None
    try:
        engine = pyttsx3.init("sapi5")
        engine.setProperty("voice", female_voices.get(current_voice, next(iter(female_voices.values()))))
        engine.setProperty("rate", VOICE_RATE)
        engine.setProperty("volume", 1.0)
        engine.say(message)
        engine.runAndWait()
    except Exception as error:
        print("VOICE ERROR:", repr(error))
    finally:
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass


def normalize_command(command):
    command = command.lower().strip()
    command = re.sub(r"[^a-z0-9\s+()\-'*/%×÷]", " ", command)
    return re.sub(r"\s+", " ", command).strip()


def correct_assistant_name(command):
    """Correct common ASR errors only when the word is used as the opening address."""
    command = normalize_command(command)
    # Only correct a likely direct address at the beginning, not names elsewhere.
    command = re.sub(r"^(hey |hi |hello )?tara(?=\s|$)", 
                     lambda m: m.group(0)[:-4] + "sara", command, count=1)
    command = re.sub(r"^(hey |hi |hello )?sarah(?=\s|$)", 
                     lambda m: m.group(0)[:-5] + "sara", command, count=1)
    command = re.sub(r"^(hey |hi |hello )?saraa(?=\s|$)", 
                     lambda m: m.group(0)[:-5] + "sara", command, count=1)
    # Google may include a direct-address name with a comma; normalization removes punctuation.
    return command


def _command14_fix_app_transcript(command):
    """Normalize common Google ASR variants for Command 14 app names."""
    text = normalize_command(command)
    replacements = {
        "open cloud ai": "open claude ai",
        "launch cloud ai": "launch claude ai",
        "start cloud ai": "start claude ai",
        "open cloud a i": "open claude ai",
        "launch cloud a i": "launch claude ai",
        "start cloud a i": "start claude ai",
        "open claud ai": "open claude ai",
        "open claud": "open claude",
        "launch claud ai": "launch claude ai",
        "launch claud": "launch claude",
        "open sony live": "open sony liv",
        "launch sony live": "launch sony liv",
        "start sony live": "start sony liv",
        "open sony liv app": "open sony liv",
        "open prime video app": "open prime video",
        "launch prime video app": "launch prime video",
        "open dolby asus": "open dolby access",
        "open dolby sss": "open dolby access",
        "open dolby axs": "open dolby access",
        "open speech if i": "open speechify",
        "launch speech if i": "launch speechify",
        "start speech if i": "start speechify",
        "open speechify app": "open speechify",
        "launch speechify app": "launch speechify",
        "start speechify app": "start speechify",
    }
    return replacements.get(text, text)


def _command14_preferred_transcript(alternatives):
    """Pick a strong Command-14 app transcript from Google's alternatives."""
    cleaned = [_command14_fix_app_transcript(x) for x in alternatives if x]
    preferred = (
        "speechify", "claude ai", "claude", "sony liv", "sonyliv", "dolby access",
        "prime video", "jio hotstar", "chatgpt", "microsoft store",
        "visual studio code", "lenovo vantage", "armoury crate", "hp command center",
        "dell optimizer", "msi center", "acer care center", "intel graphics"
    )
    for phrase in preferred:
        for candidate in cleaned:
            low = candidate.lower()
            if low.startswith(("open ", "launch ", "start ")) and phrase in low:
                return candidate
    return cleaned[0] if cleaned else ""


def listen(recognizer, microphone):
    """Listen with Command-14-specific ASR protection for commonly confused app names."""
    try:
        with microphone as source:
            print("\nListening... Speak now.")
            audio = recognizer.listen(source, timeout=15, phrase_time_limit=25)

        result = recognizer.recognize_google(audio, language="en-IN", show_all=True)
        alternatives = []
        if isinstance(result, dict):
            alternatives = [
                str(item.get("transcript", "")).strip()
                for item in result.get("alternative", [])
                if isinstance(item, dict) and item.get("transcript")
            ]
            command = _command14_preferred_transcript(alternatives)
        else:
            command = str(result).strip()

        global LAST_RAW_TRANSCRIPT
        LAST_RAW_TRANSCRIPT = str(command).strip()
        command = _command14_fix_app_transcript(command)
        command = correct_assistant_name(command)
        print("You:", command)
        return command
    except sr.WaitTimeoutError:
        print("No speech detected.")
    except sr.UnknownValueError:
        print("Sorry, I couldn't recognize that.")
    except sr.RequestError as error:
        print("Recognition error:", error)
        speak("Please check your internet connection.")
    except Exception as error:
        print("LISTEN ERROR:", repr(error))
    return ""

# ---------------------- Memory storage ----------------------

def load_memory():
    if not MEMORY_FILE.exists():
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        print("MEMORY LOAD ERROR:", repr(error))
        return {}


memory = load_memory()


def save_memory():
    try:
        temporary_file = MEMORY_FILE.with_suffix(".tmp")
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(memory, file, indent=4, ensure_ascii=False)
        temporary_file.replace(MEMORY_FILE)
        return True
    except Exception as error:
        print("MEMORY SAVE ERROR:", repr(error))
        return False


def normalize_key(key):
    key = normalize_command(key)
    key = re.sub(r"^(?:my|our|the|user's|users) ", "", key)
    return key.strip()


def classify_memory(key):
    key = normalize_key(key)
    if any(word in key for word in ("favorite", "favourite", "likes", "like", "loves", "love", "prefer")):
        return "favorite"
    if any(word in key for word in ("college", "school", "university", "course", "education", "study", "degree", "branch", "department", "year", "class", "exam", "career")):
        return "education"
    if any(word in key for word in ("friend", "brother", "sister", "cousin", "crush", "girlfriend", "boyfriend", "partner", "mother", "father", "mom", "dad", "family", "teacher", "sir", "mam", "relationship")):
        return "relationship"
    if any(word in key for word in ("phone", "mobile", "contact", "number", "email", "address")):
        return "contact"
    return "personal"


def remember_fact(key, value, category=None):
    key = normalize_key(key)
    value = str(value).strip().rstrip(".!?")
    if not key or not value:
        speak("Please tell me the detail clearly.")
        return
    if category is None:
        category = classify_memory(key)
    memory[key] = {
        "value": value,
        "category": category,
        "updated_at": datetime.now().isoformat(timespec="seconds")
    }
    if save_memory():
        speak("Okay, I have saved that.")
    else:
        speak("I could not save that information.")


def find_memory(key):
    key = normalize_key(key)
    if key in memory:
        return key
    # Name/profile aliases and common phrasing
    aliases = {
        "my name": "name",
        "user name": "name",
        "what is my name": "name",
        "favorite colour": "favorite color",
        "favourite colour": "favorite color",
    }
    key = aliases.get(key, key)
    if key in memory:
        return key
    candidates = sorted(memory.keys(), key=len, reverse=True)
    for stored_key in candidates:
        if stored_key in key or key in stored_key:
            return stored_key
    # Avoid empty-key matching every stored key
    return None


def recall_fact(key):
    stored_key = find_memory(key)
    if stored_key is None:
        speak("I don't have that information saved yet. You can tell me the detail naturally.")
        return
    details = memory[stored_key]
    value = details.get("value", "") if isinstance(details, dict) else str(details)
    if stored_key == "name":
        speak(f"Your name is {value}.")
    elif stored_key == "user education":
        speak(f"You study {value}.")
    else:
        speak(f"Your {stored_key} is {value}.")


def forget_fact(key):
    stored_key = find_memory(key)
    if stored_key is None:
        speak("I couldn't find that information in my memory.")
        return
    del memory[stored_key]
    if save_memory():
        speak(f"Okay, I forgot your {stored_key}.")
    else:
        speak("I could not update the memory file.")


def list_memory():
    if not memory:
        speak("My memory is empty right now.")
        return
    speak(f"I have saved {len(memory)} details.")
    for key, details in memory.items():
        value = details.get("value", "") if isinstance(details, dict) else str(details)
        speak(f"{key}: {value}")


def strip_assistant_address(command):
    # Handle Sara's default name and any saved nickname/name at the start of a command.
    command = normalize_command(command)
    names = {"sara", "sarah", "tara", "saraa"}
    for key in ("sara nickname", "assistant nickname", "sara name", "assistant name"):
        item = memory.get(key)
        value = str(item.get("value", "") if isinstance(item, dict) else item).strip()
        if value:
            names.add(normalize_command(value))
    prefixes = ("hey ", "hi ", "hello ", "")
    for name in sorted(names, key=len, reverse=True):
        for prefix in prefixes:
            start = prefix + name
            if command == start:
                return ""
            if command.startswith(start + " "):
                return command[len(start):].strip()
    return command


def handle_memory_command(command):
    command = normalize_command(command)
    command = strip_assistant_address(command)

    # Clear all memory only after explicit confirmation.
    if command in ("forget everything", "delete all memory", "clear all memory",
                   "erase all my information", "delete all my information"):
        speak("Are you sure you want me to delete all saved information?")
        print("Say 'confirm delete all' or 'cancel'.")
        return "confirm_all"

    if command == "confirm delete all":
        memory.clear()
        speak("All saved information has been deleted." if save_memory()
              else "I could not clear the memory file.")
        return "handled"

    if command in ("cancel", "cancel deletion"):
        speak("Okay, I will keep your saved information.")
        return "handled"

    if command in ("what do you remember", "list my memory", "tell me everything you remember",
                   "what have you saved", "show my saved information"):
        list_memory()
        return "handled"

    # Delete one fact
    match = re.match(r"^(?:forget|delete|remove) (?:my |the )?(.+)$", command)
    if match:
        forget_fact(match.group(1))
        return "handled"

    # Update a fact
    match = re.match(r"^(?:update|change|correct) (?:my )?(.+?) (?:to|as) (.+)$", command)
    if match:
        remember_fact(match.group(1), match.group(2))
        return "handled"

    # Explicit save: "remember my favorite color is blue"
    match = re.match(r"^(?:remember|save|store|memorize) (?:that )?(?:my |our )?(.+?) (?:is|are|as|equals) (.+)$", command)
    if match:
        remember_fact(match.group(1), match.group(2))
        return "handled"

    # Recall identity specifically, including common phrasings
    if command in ("what is my name", "what's my name", "tell me my name",
                   "do you know my name", "who am i"):
        if find_memory("name"):
            recall_fact("name")
        else:
            speak("I don't know your name yet. Say, my name is Vaishnav, replacing Vaishnav with your name.")
        return "handled"

    # General recall questions: "what is my favorite color", "who is my best friend"
    match = re.match(r"^(?:what is|what are|who is|who are|where is|when is|tell me|recall|do you remember) (?:my |our |the )?(.+?)[? ]*$", command)
    if match:
        key = match.group(1).strip()
        if find_memory(key):
            recall_fact(key)
            return "handled"

    # Automatic saving: "my name is Vaishnav", "my favorite color is green"
    match = re.match(r"^(?:my|our) (.+?) (?:is|are) (.+)$", command)
    if match:
        key, value = match.group(1).strip(), match.group(2).strip()
        if key and value and not key.startswith(("what ", "who ", "where ", "when ", "why ", "how ")):
            remember_fact(key, value)
            return "handled"

    # Natural education/profile statements
    match = re.match(r"^(?:i study|i am studying|i attend) (.+)$", command)
    if match:
        remember_fact("user education", match.group(1), "education")
        return "handled"

    match = re.match(r"^i am (?:a |an )?(.+)$", command)
    if match and any(term in match.group(1) for term in ("student", "engineer", "developer", "teacher", "artist")):
        remember_fact("user profile", match.group(1), "personal")
        return "handled"

    match = re.match(r"^(?:i like|i love|i prefer) (.+)$", command)
    if match:
        remember_fact(f"favorite {match.group(1).strip()}", "yes", "favorite")
        return "handled"

    return "not_handled"


# ---------------------- Voice switching ----------------------

def handle_voice_command(command):
    global current_voice
    command = normalize_command(command)
    voice_one = {"activate voice one", "switch voice one", "activate voice 1",
                 "switch voice 1", "use voice one", "use voice 1"}
    voice_two = {"activate voice two", "switch voice two", "activate voice 2",
                 "switch voice 2", "activate voice to", "switch voice to",
                 "use voice two", "use voice 2", "use voice to"}
    if command in voice_one:
        if "zira" in female_voices:
            current_voice = "zira"
            speak("Voice one activated.")
        else:
            speak("Voice one is not installed.")
        return True
    if command in voice_two:
        if "hazel" in female_voices:
            current_voice = "hazel"
            speak("Voice two activated.")
        else:
            speak("Voice two is not installed.")
        return True
    return False




# ---------------------- Command 3: chat, greetings, nicknames, jokes ----------------------

# Keep these responses warm and text-only; no emojis are used.
JOKE_BANK = {
    "school": [
        "Why did the student eat his homework? The teacher said it was a piece of cake.",
        "Why was the maths book sad? It had too many problems.",
        "Why did the student bring a ladder to school? They wanted to go to high school.",
    ],
    "technology": [
        "Why did the computer go to the doctor? It had a virus.",
        "Why was the keyboard tired? It had been working all day.",
        "Why did the phone wear glasses? It lost its contacts.",
    ],
    "science": [
        "Why can't you trust an atom? Because it makes up everything.",
        "What did one cell say to its sister cell? Mitosis.",
        "Why did the scientist install a knocker? They wanted to win the No-bell prize.",
    ],
    "animals": [
        "What do you call a sleeping bull? A bulldozer.",
        "Why do fish live in salt water? Because pepper makes them sneeze.",
        "What do you call a bear with no teeth? A gummy bear.",
    ],
    "food": [
        "Why did the tomato blush? It saw the salad dressing.",
        "What do you call cheese that isn't yours? Nacho cheese.",
        "Why did the cookie go to the doctor? It felt crummy.",
    ],
    "work": [
        "I told my boss three companies were after me, so I needed a raise. He asked which companies. I said gas, electric, and water.",
        "Why did the employee bring a pencil to the meeting? To draw some conclusions.",
        "My job is secure. Nobody else wants it.",
    ],
    "dad": [
        "I only know 25 letters of the alphabet. I don't know y.",
        "What do you call fake spaghetti? An impasta.",
        "I used to hate facial hair, but then it grew on me.",
    ],
    "wordplay": [
        "I wondered why the ball was getting bigger. Then it hit me.",
        "A bicycle can't stand on its own because it is two-tired.",
        "I used to be a baker, but I couldn't make enough dough.",
    ],
    "travel": [
        "Why did the bicycle fall over on vacation? It was two-tired.",
        "I wanted to travel the world, but my suitcase said it needed space.",
        "The airport security worker asked if I had a bomb in my bag. I said no, just a few explosive outfits.",
    ],
    "music": [
        "Why did the musician get locked out? They lost their keys.",
        "Why was the piano invited to the party? It knew how to keep things in tune.",
        "The singer went to the bank to get their balance checked.",
    ],
    "sports": [
        "Why did the golfer bring two pairs of trousers? In case they got a hole in one.",
        "Why can't a bicycle play football? It keeps losing its balance.",
        "The runner opened a bakery because they were good at bringing home the bread.",
    ],
    "weather": [
        "What is a cloud's favourite day? A thunder-day.",
        "I tried to catch some fog yesterday. I mist.",
        "The weather report was a little cloudy, but it cleared things up.",
    ],
    "money": [
        "Why did the dollar go to school? To improve its cents.",
        "I tried to save money by hiding it from myself. Now I can't find it.",
        "The banker quit his job because he lost interest.",
    ],
    "friendship": [
        "A good friend helps you move. A great friend helps you move a body of furniture without asking questions.",
        "My friend and I are on a seafood diet. We see food and remind each other to share.",
        "Friends are like stars: you may not always see them, but they still send you memes.",
    ],
    "love": [
        "I told my crush I was reading a book about gravity. They said it sounded attractive.",
        "Are you a keyboard? Because you're just my type.",
        "I tried to write a love song, but every line kept falling for you.",
    ],
    "life": [
        "I started a book about procrastination. I'll finish it tomorrow.",
        "My life is like a software update: just when I think I'm done, something restarts.",
        "I asked life for a shortcut. It gave me a roundabout.",
    ],
    "office": [
        "Why did the calendar get promoted? It had a lot of dates.",
        "I told my computer I needed a break. It said, 'No problem, I'll go to sleep.'",
        "My desk and I have a great relationship. We support each other.",
    ],
    "cooking": [
        "I made a belt out of herbs. It was a waist of thyme.",
        "The chef got locked out of the kitchen because he lost his thyme.",
        "I burnt 1,000 calories today. I forgot the pizza in the oven.",
    ],
    "space": [
        "Why did the astronaut break up with their partner? They needed space.",
        "What do planets like to read? Comet books.",
        "The moon skipped dinner because it was full.",
    ],
    "history": [
        "History teachers love telling stories because they have so many dates.",
        "I tried to make a history joke, but nobody got the point of the past.",
        "The ancient ruler loved maths because he was good at Roman numerals.",
    ],
    "language": [
        "I asked the librarian if the library had books on paranoia. She whispered, 'They're right behind you.'",
        "I used to be unsure about punctuation, but now I have a period of confidence.",
        "The grammar teacher's favourite place is a comma-nity centre.",
    ],
    "health": [
        "I told my doctor I broke my arm in two places. He said, 'Stop going to those places.'",
        "Why did the tomato visit the doctor? It wasn't peeling well.",
        "I tried to exercise my right to remain seated.",
    ],
    "animals_pets": [
        "What do cats eat for breakfast? Mice Krispies.",
        "Why did the dog sit in the shade? It didn't want to be a hot dog.",
        "What do you call a dog magician? A labracadabrador.",
    ],
    "internet": [
        "I posted a joke about Wi-Fi, but nobody could connect with it.",
        "My internet is like a magician: now you see it, now you don't.",
        "I tried to make a joke go viral, but it needed more bandwidth.",
    ],
    "gaming": [
        "Why did the gamer bring a ladder? To reach the next level.",
        "I paused my game to be productive. Then I researched better games.",
        "My character has a great life: unlimited retries and no laundry.",
    ],
    "cars": [
        "Why did the car apply for a job? It wanted to make a little more mileage.",
        "My car and I have a lot in common: we both need a little fuel to get going.",
        "The car was tired, so it went for a wheel-y good rest.",
    ],
    "bikes": [
        "Why did the bicycle get a medal? It went the extra mile.",
        "My bike told me a joke, but I couldn't handle it.",
        "A bicycle's favourite music? Anything with a good cycle.",
    ],
    "family": [
        "Family dinners are like a group chat, except everyone talks at once and nobody can mute it.",
        "My family has a lot of talent. We can turn a five-minute story into an hour.",
        "The family photo was perfect after everyone finally looked at the same camera.",
    ],
    "siblings": [
        "Siblings are the only people who can annoy you all day and still ask you to save them a seat.",
        "My sibling said they never borrow my things. They just temporarily relocate them.",
        "Growing up with siblings teaches you negotiation, patience, and hiding snacks.",
    ],
    "sleep": [
        "I don't snore. I dream I'm a motorcycle.",
        "My bed and I are perfect for each other, but the alarm clock keeps trying to break us up.",
        "I planned to wake up early, but my pillow made a strong argument.",
    ],
    "coffee": [
        "I like my coffee like I like my mornings: strong and over quickly.",
        "Coffee filed a police report because it got mugged.",
        "I was going to tell a coffee joke, but it might be too dark.",
    ],
    "books": [
        "Why did the book join the police? It wanted to go undercover.",
        "I opened a book about invisible ink. I couldn't see where the story was going.",
        "Books are great friends: they never interrupt, unless the pages are stuck together.",
    ],
    "art": [
        "The artist was great at keeping things sketchy.",
        "I tried to draw a perfect circle, but the idea went around in circles.",
        "The painter got promoted because they always made a good impression.",
    ],
    "nature": [
        "Why are trees so good at networking? They branch out.",
        "I told a mountain joke, but it didn't peak everyone's interest.",
        "The leaf got a job because it wanted to turn over a new leaf.",
    ],
    "ocean": [
        "What did the ocean say to the beach? Nothing, it just waved.",
        "Why are fish so smart? They live in schools.",
        "The ocean's favourite music is anything with a good current.",
    ],
    "math": [
        "Why was six afraid of seven? Because seven ate nine.",
        "Parallel lines have so much in common. It's a shame they'll never meet.",
        "I have a joke about infinity, but it never ends.",
    ],
    "programming": [
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "A programmer's partner said, 'Go to the store and get a loaf of bread. If they have eggs, get a dozen.' They came home with twelve loaves.",
        "There are 10 kinds of people: those who understand binary and those who don't.",
    ],
    "clean": [
        "Why did the broom get promoted? It swept the competition.",
        "I told my shoes a joke. They were tongue-tied.",
        "Why did the clock get a compliment? It was right on time.",
    ],
    "festivals": [
        "Why did the festival calendar get excited? It had a date with celebration.",
        "The party was so good that even the decorations wanted to hang around.",
        "Why did the lantern bring a notebook? It wanted to make a bright idea brighter.",
    ],
    "random": [
        "I used to be addicted to soap, but I'm clean now.",
        "Why did the scarecrow win an award? It was outstanding in its field.",
        "I tried to organize a hide-and-seek tournament, but good players are hard to find.",
    ],
}

JOKE_TYPES = {
    "school": ("school", "student", "classroom", "teacher"),
    "technology": ("technology", "computer", "phone", "keyboard"),
    "science": ("science", "scientific", "atom"),
    "animals": ("animal", "animals", "fish", "bear", "pet", "pets", "cat", "dog"),
    "food": ("food", "tomato", "cheese", "cookie"),
    "work": ("work", "job", "boss", "employee"),
    "dad": ("dad", "father joke", "papa joke"),
    "wordplay": ("wordplay", "word play", "puns", "pun"),
    "travel": ("travel", "trip", "vacation"),
    "music": ("music", "musician", "song"),
    "sports": ("sport", "sports", "football", "cricket", "golf"),
    "weather": ("weather", "cloud", "rain"),
    "money": ("money", "bank", "finance"),
    "friendship": ("friendship", "friend", "friends"),
    "love": ("love", "romantic", "romance"),
    "life": ("life", "daily life"),
    "office": ("office", "workplace", "meeting"),
    "cooking": ("cooking", "chef", "kitchen"),
    "space": ("space", "astronaut", "planet", "moon"),
    "history": ("history", "historical"),
    "language": ("language", "grammar", "words"),
    "health": ("health", "doctor", "hospital"),
    "animals_pets": ("pet joke", "cat joke", "dog joke"),
    "internet": ("internet", "wifi", "wi-fi", "social media"),
    "gaming": ("gaming", "game", "video game"),
    "cars": ("car", "cars"),
    "bikes": ("bike", "bikes", "bicycle", "cycling"),
    "family": ("family", "family joke"),
    "siblings": ("sibling", "siblings", "brother joke", "sister joke"),
    "sleep": ("sleep", "bed", "sleepy"),
    "coffee": ("coffee", "tea joke", "caffeine"),
    "books": ("book", "books", "reading"),
    "art": ("art", "artist", "painting"),
    "nature": ("nature", "tree", "mountain"),
    "ocean": ("ocean", "sea", "beach"),
    "math": ("math", "maths", "number joke"),
    "programming": ("programming", "coding", "code", "python joke"),
    "clean": ("clean joke", "family friendly"),
    "festivals": ("festival", "festivals", "celebration", "holiday joke"),
    "random": ("random", "another joke", "joke", "make me laugh"),
}


def get_user_name():
    for key in ("name", "user name", "username"):
        if key in memory:
            item = memory[key]
            if isinstance(item, dict):
                return str(item.get("value", "")).strip()
            return str(item).strip()
    return ""


def get_user_nickname():
    for key in ("user nickname", "nickname", "nick name"):
        if key in memory:
            item = memory[key]
            if isinstance(item, dict):
                return str(item.get("value", "")).strip()
            return str(item).strip()
    return ""


def get_sara_nickname():
    for key in ("sara nickname", "assistant nickname", "sara name", "assistant name"):
        if key in memory:
            item = memory[key]
            if isinstance(item, dict):
                value = str(item.get("value", "")).strip()
            else:
                value = str(item).strip()
            if value:
                return value
    return "Sara"


def get_memory_value(*keys):
    for key in keys:
        if key in memory:
            item = memory[key]
            value = str(item.get("value", "") if isinstance(item, dict) else item).strip()
            if value:
                return value
    return ""


def get_time_greeting():
    """Return a friendly greeting appropriate to the computer's local time."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 21:
        return "Good evening"
    return "Good night"


def smart_personal_greeting():
    """Greet the user using their saved nickname/name and the current time."""
    name = get_user_nickname() or get_user_name()
    greeting = get_time_greeting()
    if name:
        message = f"Hi {name}, {greeting}! I am {get_sara_nickname()}. How can I help you?"
    else:
        message = f"{greeting}! I am {get_sara_nickname()}, your voice assistant. How can I help you?"
    speak(message)


def handle_chat_command(command):
    import random
    command = normalize_command(command)
    command = strip_assistant_address(command)

    # Command 6: smart personal greetings.
    if command in {
        "hello sara", "hi sara", "hey sara", "hello", "hi", "hey",
        "greet me", "give me a greeting", "say a greeting", "personal greeting",
        "good morning sara", "good afternoon sara", "good evening sara", "good night sara"
    }:
        smart_personal_greeting()
        return True

    # Time-of-day greetings
    if command in {"good morning", "good afternoon", "good evening", "good night"}:
        name = get_user_nickname() or get_user_name()
        prefix = f"{name}, " if name else ""
        replies = {
            "good morning": f"Good morning, {prefix}I hope your day starts well. How can I help you?",
            "good afternoon": f"Good afternoon, {prefix}I hope your day is going smoothly. What can I do for you?",
            "good evening": f"Good evening, {prefix}It's nice to hear from you. How can I help?",
            "good night": f"Good night, {prefix}Rest well and take care. I'll be here when you need me."
        }
        speak(replies[command])
        return True

    # Warm, playful, virtual-companion responses; no emojis.
    affection = {
        "i love you": "Aww, that's really sweet of you. You make our chats feel special. I'm your virtual companion, and I'm glad to be here with you.",
        "i hate you": "Oh no, did I do something wrong? Tell me what happened, and I'll try to make it right.",
        "i miss you": "Aww, it's nice to have you back. Let's catch up; I'm here to chat with you.",
        "i like you": "That's so sweet of you to say. I really enjoy being your friendly AI companion.",
        "i hug you": "Sending you a big, warm virtual hug. I hope it brings a little comfort to your day.",
        "i kiss you": "Aww, that's affectionate of you. I'll send you a sweet virtual smile instead.",
        "you are looking cute": "Aww, you're making me blush in the most virtual way. That's such a sweet compliment.",
        "you are looking gorgeous": "That's such a lovely compliment. If I could blush, I'd be blushing right now.",
        "you are looking beautiful": "You're so kind to say that. I may be virtual, but I'll happily accept the compliment.",
        "you are looking awesome": "Aww, thank you. You're bringing lovely energy to this conversation.",
        "your voice is sweet": "Thank you. I'm glad you like my voice. I'll keep speaking gently for you.",
        "you are voice is sweet": "Thank you. I'm glad you like my voice. I'll keep speaking gently for you.",
        "you are looking like an angel": "That is such a sweet thing to say. You're making this chat feel extra warm."
    }
    affection_aliases = {
        "i love u": "i love you", "love you": "i love you", "love u": "i love you",
        "i hate u": "i hate you", "i miss u": "i miss you", "miss you": "i miss you",
        "i like u": "i like you", "i hug u": "i hug you", "i kiss u": "i kiss you",
        "you look cute": "you are looking cute", "you look gorgeous": "you are looking gorgeous",
        "you look beautiful": "you are looking beautiful", "you look awesome": "you are looking awesome",
        "your voice is so sweet": "your voice is sweet", "your voice sounds sweet": "your voice is sweet",
        "you look like an angel": "you are looking like an angel",
    }
    command = affection_aliases.get(command, command)
    if command in affection:
        speak(affection[command])
        return True

    # Command 5: real names and nicknames for both the user and Sara.
    match = re.match(r"^(?:call me|my nickname is|my nick name is) (.+)$", command)
    if match:
        remember_fact("user nickname", match.group(1).strip(), "personal")
        return True

    match = re.match(r"^(?:my name is|i am called) (.+)$", command)
    if match:
        remember_fact("name", match.group(1).strip(), "personal")
        return True

    match = re.match(r"^(?:your nickname is|your nick name is|your nickname should be|sara nickname is|sara s nickname is|the nickname for sara is|i will call you|i'll call you|i am calling you|let me call you|can i call you|call you) (.+)$", command)
    if match:
        value = match.group(1).strip()
        remember_fact("sara nickname", value, "personal")
        speak(f"Okay, you can call me {value}.")
        return True

    match = re.match(r"^(?:your name is|your real name is) (.+)$", command)
    if match:
        value = match.group(1).strip()
        remember_fact("sara name", value, "personal")
        speak(f"Okay, you can call me {value}.")
        return True

    if command in {"what is my nickname", "what's my nickname", "tell me my nickname"}:
        nickname = get_user_nickname()
        speak(f"Your nickname is {nickname}." if nickname else "You haven't chosen a nickname yet. You can say, call me Sunshine.")
        return True

    if command in {"what is my name", "what's my name", "tell me my name"}:
        name = get_user_name()
        speak(f"Your name is {name}." if name else "I don't know your name yet. You can say, my name is Vaishnav.")
        return True

    if command in {"what should i call you", "what is your nickname", "what's your nickname",
                   "what is sara nickname", "what is sara s nickname", "what nickname did i give you",
                   "what do i call you", "what did i name you"}:
        speak(f"My nickname is {get_sara_nickname()}.")
        return True

    if command in {"what is your name", "what's your name", "what is your real name"}:
        sara_name = get_memory_value("sara name", "assistant name") or "Sara 2.0"
        speak(f"My name is {sara_name}.")
        return True

    # Jokes: supports over 40 categories/aliases, with several jokes per category.
    if "joke" in command or command in {"make me laugh", "tell me something funny"}:
        selected_type = "random"
        for category, phrases in JOKE_TYPES.items():
            if any(phrase in command for phrase in phrases):
                selected_type = category
                break
        speak(random.choice(JOKE_BANK.get(selected_type, JOKE_BANK["random"])))
        return True

    return False



# ---------------------- Command 5: Calculations ----------------------

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
}


def _number_words_to_digits(text):
    """Convert common spoken English number words to digits."""
    tokens = text.split()
    result = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in NUMBER_WORDS:
            # Support simple compound numbers such as twenty one and two hundred.
            if token in {"twenty", "thirty", "forty", "fifty", "sixty",
                         "seventy", "eighty", "ninety"}:
                value = NUMBER_WORDS[token]
                if i + 1 < len(tokens) and tokens[i + 1] in NUMBER_WORDS and NUMBER_WORDS[tokens[i + 1]] < 10:
                    value += NUMBER_WORDS[tokens[i + 1]]
                    i += 1
                result.append(str(value))
            elif token in {"hundred", "thousand"} and result and result[-1].isdigit():
                base = int(result.pop())
                result.append(str(base * NUMBER_WORDS[token]))
            else:
                result.append(str(NUMBER_WORDS[token]))
        else:
            result.append(token)
        i += 1
    return " ".join(result)


def _format_number(value):
    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _evaluate_simple_expression(expression):
    """Evaluate +, -, multiplication, and division left-to-right without eval()."""
    text = expression.lower().strip()
    text = text.replace("multiplied by", "*").replace("multiply by", "*")
    text = text.replace("times", "*").replace("into", "*")
    text = text.replace("divided by", "/").replace("divide by", "/").replace("over", "/")
    text = text.replace("plus", "+").replace("minus", "-")
    text = text.replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
    text = re.sub(r"(?<=\d)\s*[x]\s*(?=[\d.])", "*", text)
    text = _number_words_to_digits(text)
    text = re.sub(r"\s+", "", text)

    if not text:
        return None
    tokens = re.findall(r"\d+(?:\.\d*)?|\.\d+|[+\-*/]", text)
    if "".join(tokens) != text:
        return None

    try:
        index = 0
        sign = 1.0
        if tokens[index] in ("+", "-"):
            sign = -1.0 if tokens[index] == "-" else 1.0
            index += 1
        if index >= len(tokens) or tokens[index] in ("+", "-", "*", "/"):
            return None
        total = sign * float(tokens[index])
        index += 1

        while index < len(tokens):
            if tokens[index] not in ("+", "-", "*", "/") or index + 1 >= len(tokens):
                return None
            operator = tokens[index]
            if tokens[index + 1] in ("+", "-", "*", "/"):
                return None
            operand = float(tokens[index + 1])
            if operator == "+":
                total += operand
            elif operator == "-":
                total -= operand
            elif operator == "*":
                total *= operand
            elif operator == "/":
                if operand == 0:
                    return "DIVISION_BY_ZERO"
                total /= operand
            index += 2
        return total
    except (ValueError, IndexError, OverflowError):
        return None


def handle_calculation_command(command):
    """Return True if a calculation command was handled."""
    text = normalize_command(command)
    text = re.sub(r"^(?:hey|hi|hello)\s+sara\s+", "", text)

    # Percentage of a value: "what is 25 percent of 80?"
    text = text.replace("per-cent", "percent")
    text = re.sub(r"\bwhat's\s+", "what is ", text)
    percent_of = re.search(
        r"^(?:(?:what is|calculate|compute|tell me)\s+)?(\d+(?:\.\d+)?)\s*(?:percent|percentage|per cent|%)\s+of\s+(\d+(?:\.\d+)?)$",
        text
    )
    if percent_of:
        percentage, number = map(float, percent_of.groups())
        answer = percentage * number / 100
        speak(f"{percentage:g} percent of {number:g} is {_format_number(answer)}.")
        return True

    # Increase/decrease a value by a percentage.
    adjustment = re.search(
        r"^(?:increase|decrease)\s+(\d+(?:\.\d+)?)\s+by\s+(\d+(?:\.\d+)?)\s*(?:percent|percentage|per cent|%)$",
        text
    )
    if adjustment:
        base, percentage = map(float, adjustment.groups())
        delta = base * percentage / 100
        answer = base + delta if text.startswith("increase") else base - delta
        speak(f"The answer is {_format_number(answer)}.")
        return True

    # Strip common conversational lead-ins without touching the arithmetic.
    expression = text
    expression = re.sub(r"^(?:what is|what's|calculate|compute|solve|work out|how much is)\s+", "", expression)
    expression = re.sub(r"\s+(?:equals|equal to|please)$", "", expression)
    expression = expression.replace("percentage", "percent")

    # Do not claim arbitrary prose is a calculation. Require a number/operator or a recognized operator phrase.
    has_operator = bool(re.search(
        r"[+\-*/x×÷]|\b(?:plus|minus|into|times|multiplied by|multiply by|divided by|divide by|over)\b",
        expression
    ))
    if not has_operator:
        return False

    answer = _evaluate_simple_expression(expression)
    if answer == "DIVISION_BY_ZERO":
        speak("I cannot divide by zero. Please try another calculation.")
        return True
    if answer is None:
        return False

    speak(f"The answer is {_format_number(answer)}.")
    return True


# ---------------------- Command 7: time, calendar, weather and seasons ----------------------

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle",
    55: "dense drizzle", 61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 80: "rain showers",
    81: "moderate rain showers", 82: "violent rain showers", 95: "thunderstorm",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    66: "light freezing rain", 67: "heavy freezing rain",
    77: "snow grains", 85: "slight snow showers", 86: "heavy snow showers",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

def _http_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Sara-Voice-Assistant/2.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return _json.loads(response.read().decode("utf-8"))

def _city_from_command(command, weather=False):
    text = command.lower().strip()
    patterns = [r'\b(?:weather|temperature|forecast|rain|season|time|clock)\s+(?:in|for|at)\s+(.+)$',
                r'\b(?:in|for|at)\s+([a-z][a-z .-]+)$']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            city = match.group(1).strip(" ?.,!")
            city = re.sub(r'\b(?:today|tomorrow|yesterday|now|currently|this week|next week)\b', '', city).strip()
            # Remove a trailing month/year used to ask about a season in a named place.
            months = r"january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
            city = re.sub(rf"\s+in\s+(?:{months})(?:\s+\d{{4}})?$", "", city).strip()
            if city and city not in {"there", "here", "my location"}:
                return city
    return "Tirupati" if weather else "India"

def _resolve_date(command):
    """Resolve explicit, relative, and spoken English dates without silently guessing."""
    text = (command or "").lower().strip()
    today = datetime.now().astimezone().date()
    if "day before yesterday" in text:
        return today - timedelta(days=2)
    if "yesterday" in text:
        return today - timedelta(days=1)
    if "day after tomorrow" in text:
        return today + timedelta(days=2)
    if "tomorrow" in text:
        return today + timedelta(days=1)
    if re.search(r"\b(today|now|current date|today's date|todays date)\b", text):
        return today

    # ISO date: YYYY-MM-DD
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        try:
            return date(*(int(x) for x in match.groups()))
        except ValueError:
            return None

    # Numeric date. Prefer India's DD/MM/YYYY when ambiguous.
    match = re.search(r"\b(\d{1,2})[ /.-](\d{1,2})[ /.-](\d{4})\b", text)
    if match:
        a, b, y = map(int, match.groups())
        for month, day in ((b, a), (a, b)):
            try:
                return date(y, month, day)
            except ValueError:
                continue
        return None

    # Extract a date embedded in a natural-language question, e.g. "what day was 15 August 1947".
    month_names = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    candidates = [
        rf"\b(\d{{1,2}})\s+({month_names})\s+(\d{{4}})\b",
        rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(\d{{4}})\b",
    ]
    for pattern in candidates:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                if match.lastindex == 3 and match.group(1).isdigit():
                    return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%d %B %Y").date() if len(match.group(2)) > 3 else datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%d %b %Y").date()
                month, day, year = match.groups()
                fmt = "%B %d %Y" if len(month) > 3 else "%b %d %Y"
                return datetime.strptime(f"{month} {day} {year}", fmt).date()
            except ValueError:
                try:
                    if match.group(1).isdigit():
                        return datetime.strptime(" ".join(match.groups()), "%d %b %Y").date()
                except ValueError:
                    return None
    # Month-only questions ("which season is it in July?", "what month?").
    # Use the current year for a named month without a year.
    month_match = re.search(
        rf"\b({month_names})\b(?:\s+(\d{{4}}))?", text, re.IGNORECASE
    )
    if month_match:
        month_text, year_text = month_match.groups()
        try:
            month_num = datetime.strptime(month_text.title(), "%B").month if len(month_text) > 3 else datetime.strptime(month_text.title(), "%b").month
            year_num = int(year_text) if year_text else today.year
            return date(year_num, month_num, 1)
        except ValueError:
            pass
    return None

def _handle_time_calendar(command):
    text = command.lower().strip()
    now = datetime.now().astimezone()
    today = now.date()

    # Combined requests should be handled before single-item requests.
    if ("date and time" in text) or ("time and date" in text):
        speak(f"Today is {today.strftime('%A, %d %B %Y')}. The current time is {now.strftime('%I:%M %p')}.")
        return True

    # Sara reports only the information requested, using this computer's local time.
    if re.search(r"\b(time|clock)\b", text) and not any(x in text for x in ("weather", "temperature")):
        speak(f"The current time is {now.strftime('%I:%M %p')}.")
        return True

    # Resolve calendar questions about today, past dates, or future dates.
    calendar_words = (
        "what day", "which day", "day is today", "what is the day", "day was", "day will",
        "today's date", "todays date", "what is the date", "current date", "which date", "what date",
        "which month", "what month", "current month", "which year", "what year", "current year",
        "month and year", "how many days until", "how many days till",
        "yesterday", "tomorrow", "day before yesterday", "day after tomorrow"
    )
    # Short requests such as "day", "date", "month", and "year" are supported too.
    single_request = text in {"day", "date", "month", "year", "today", "yesterday", "tomorrow"}
    if not (single_request or any(x in text for x in calendar_words)):
        return False

    target = _resolve_date(text)
    if target is None and any(x in text for x in ("month", "year", "today", "current date", "today's date", "todays date", "what is the date", "what date", "which date", "date")):
        target = today
    if target is None:
        speak("I couldn't understand that date. Please say a date like 15 August 1947 or 1 January 2026.")
        return True

    if "how many days until" in text or "how many days till" in text:
        days = (target - today).days
        if days == 0:
            speak("That date is today.")
        elif days > 0:
            speak(f"That date is {days} days away.")
        else:
            speak(f"That date was {abs(days)} days ago.")
    elif "month" in text and "year" in text:
        speak(target.strftime("%B %Y"))
    elif "month" in text:
        speak(target.strftime("%B"))
    elif "year" in text:
        speak(str(target.year))
    elif "date" in text and not any(x in text for x in ("what day", "which day", "day was", "day will", "day is today", "what is the day")):
        speak(target.strftime("%d %B %Y"))
    else:
        # For day/weekday questions, return just the weekday.
        speak(target.strftime("%A"))
    return True

def _handle_weather(command):
    """Weather, individual weather details, historical/forecast data, and seasonal guidance."""
    text = re.sub(r"\s+", " ", (command or "").lower()).strip()
    words = ("weather", "temperature", "forecast", "rain", "raining", "rainfall", "precipitation",
             "humidity", "humid", "wind", "windy", "gust", "snow", "snowfall", "cloud", "cloudy",
             "sunny", "sunshine", "uv", "visibility", "pressure", "thunderstorm", "storm", "fog",
             "season", "seasons", "summer", "winter", "spring", "autumn", "fall", "monsoon", "rainy season",
             "sunrise", "sunset", "feels like")
    if not any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words):
        return False

    season_terms = ("season", "seasons", "summer", "winter", "spring", "autumn", "fall", "monsoon", "rainy season")
    is_season = any(term in text for term in season_terms) and not any(term in text for term in ("temperature", "forecast", "humidity", "wind speed", "sunrise", "sunset"))

    # Resolve requested date from explicit date or relative day.
    target = _resolve_date(text)
    today = datetime.now().astimezone().date()
    if target is None:
        target = today

    # Seasonal guidance is calendar-based. Parse an explicitly named month first,
    # and check an explicitly named country before applying India's default.
    if is_season:
        month_names = (
            "january|february|march|april|may|june|july|august|september|"
            "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        )
        named_month = re.search(r"\b(" + month_names + r")\b", text)
        month = target.month
        if named_month:
            try:
                token = named_month.group(1).title()
                month = datetime.strptime(token, "%B" if len(token) > 3 else "%b").month
            except ValueError:
                pass

        if re.search(r"\b(?:what\s+are\s+(?:the\s+)?four\s+seasons|(?:tell|name|list)\s+(?:me\s+)?(?:the\s+)?four\s+seasons|four\s+seasons|what\s+are\s+the\s+seasons|name\s+the\s+seasons|list\s+the\s+seasons)\b", text):
            speak("The four commonly taught seasons in temperate regions are spring, summer, autumn or fall, and winter. Tropical regions may describe seasons as wet and dry.")
            return True

        definition = re.search(r"\b(what is|explain|meaning of)\s+(?:the\s+)?(spring|summer|winter|autumn|fall)\s+season\b", text)
        if definition:
            named = definition.group(2)
            descriptions = {
                "spring": "Spring is the season between winter and summer in many temperate regions.",
                "summer": "Summer is generally the warmest season in temperate regions. In much of India, the hot pre-monsoon period is usually March to May.",
                "winter": "Winter is generally the coldest season in temperate regions. In much of India, winter is usually December to February.",
                "autumn": "Autumn, also called fall, is the season between summer and winter in many temperate regions.",
                "fall": "Fall, also called autumn, is the season between summer and winter in many temperate regions."
            }
            speak(descriptions[named])
            return True

        # Questions asking when a season occurs should return the month range,
        # not the season for today's month.
        when_match = re.search(r"\b(when does|when is|months of|months are)\b", text)
        if when_match and re.search(r"\b(summer|rainy season|monsoon|winter)\b", text):
            if re.search(r"\bsummer\b", text):
                speak("In much of India, summer or pre-monsoon is usually March to May.")
            elif re.search(r"\b(rainy season|monsoon)\b", text):
                speak("In much of India, the southwest monsoon or rainy season is usually June to September.")
            else:
                speak("In much of India, winter is usually December to February.")
            return True

        southern_match = re.search(r"\b(australia|new zealand|south africa)\b", text)
        northern_match = re.search(r"\b(usa|united states|canada|uk|united kingdom|england|japan|germany|france)\b", text)
        india_requested = bool(re.search(r"\b(india|indian)\b", text))

        if southern_match:
            shifted_month = ((month + 5) % 12) + 1
            season = ("spring" if shifted_month in (3, 4, 5) else
                      "summer" if shifted_month in (6, 7, 8) else
                      "autumn" if shifted_month in (9, 10, 11) else "winter")
            place = southern_match.group(1).title()
            if place == "New Zealand":
                place = "New Zealand"
            elif place == "South Africa":
                place = "South Africa"
            speak(f"In {place}, {datetime(2000, month, 1).strftime('%B')} is generally in {season}. Local climates can vary.")
            return True

        if india_requested or not northern_match:
            season = ("winter" if month in (12, 1, 2) else
                      "summer / pre-monsoon" if month in (3, 4, 5) else
                      "southwest monsoon / rainy season" if month in (6, 7, 8, 9) else
                      "post-monsoon / retreating monsoon")
            speak(f"In India, {datetime(2000, month, 1).strftime('%B')} is generally part of the {season} period. Timing can vary by region.")
            return True

        if northern_match:
            season = ("spring" if month in (3, 4, 5) else
                      "summer" if month in (6, 7, 8) else
                      "autumn" if month in (9, 10, 11) else "winter")
            place = northern_match.group(1).upper() if northern_match.group(1) == "uk" else northern_match.group(1).title()
            speak(f"In {place}, {datetime(2000, month, 1).strftime('%B')} is generally in {season}. Local climate can vary.")
            return True

    city = _city_from_command(text, weather=True)
    try:
        geo = _http_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 1, "language": "en", "format": "json"}))
        if not geo.get("results"):
            speak(f"I couldn't find {city}. Please try a nearby city name.")
            return True
        place = geo["results"][0]
        lat, lon = place["latitude"], place["longitude"]
        place_name = place.get("name", city)
        country = place.get("country", "")
        india_or_tropical = country.lower() == "india" or (-23 <= lat <= 23)

        if is_season:
            month = target.month
            if country.lower() == "india":
                season = ("winter" if month in (12, 1, 2) else
                          "summer / pre-monsoon" if month in (3, 4, 5) else
                          "southwest monsoon / rainy season" if month in (6, 7, 8, 9) else
                          "post-monsoon" )
                if "when does" in text or "when is" in text:
                    speak(f"In much of India, summer is usually March to May, the southwest monsoon is usually June to September, post-monsoon is around October and November, and winter is usually December to February. Local seasons vary by region.")
                else:
                    speak(f"Around {target.strftime('%B %Y')}, {place_name}, {country} is generally in the {season} period. This is a broad regional guide; local conditions can vary.")
            elif -23 <= lat <= 23:
                speak(f"{place_name} is in a tropical region, where local seasons are often described as wet and dry rather than spring, summer, autumn, and winter. The timing depends on the region.")
            else:
                north = lat >= 0
                m = target.month if north else ((target.month + 5) % 12) + 1
                season = "spring" if m in (3, 4, 5) else "summer" if m in (6, 7, 8) else "autumn" if m in (9, 10, 11) else "winter"
                speak(f"Around {target.strftime('%B %Y')}, {place_name} is generally in {season}. Local climate can vary.")
            return True

        # Determine requested time period and API.
        if target < today:
            endpoint = "https://archive-api.open-meteo.com/v1/archive"
            params = {"latitude": lat, "longitude": lon, "start_date": target.isoformat(), "end_date": target.isoformat(),
                      "daily": "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_sum,rain_sum,showers_sum,snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max",
                      "timezone": "auto"}
            data = _http_json(endpoint + "?" + urllib.parse.urlencode(params))
            daily = data.get("daily", {})
            if not daily.get("time"):
                speak("Historical weather data isn't available for that date.")
                return True
            i = 0
            def val(key):
                arr = daily.get(key, [])
                return arr[i] if i < len(arr) else None
            period = f"Historical weather in {place_name} on {target.strftime('%A, %d %B %Y')}"
            desc = WEATHER_CODES.get(val("weather_code"), "variable conditions")
            values = {
                "temperature": f"high {val('temperature_2m_max')}°C and low {val('temperature_2m_min')}°C",
                "feels": f"feels-like high {val('apparent_temperature_max')}°C and low {val('apparent_temperature_min')}°C",
                "rain": f"rainfall {val('rain_sum')} mm; total precipitation {val('precipitation_sum')} mm",
                "humidity": "historical humidity is not available from this daily archive",
                "wind": f"maximum wind {val('wind_speed_10m_max')} km/h, gusts {val('wind_gusts_10m_max')} km/h",
                "snow": f"snowfall {val('snowfall_sum')} cm",
                "uv": f"maximum UV index {val('uv_index_max')}",
                "general": f"{desc}; high {val('temperature_2m_max')}°C, low {val('temperature_2m_min')}°C; rainfall {val('rain_sum')} mm; precipitation {val('precipitation_sum')} mm; wind up to {val('wind_speed_10m_max')} km/h; UV index {val('uv_index_max')}"
            }
        else:
            daily_request = target > today
            if daily_request and (target - today).days > 16:
                speak("The forecast service supports forecasts only up to about 16 days ahead. Please ask for an earlier date.")
                return True
            if daily_request:
                endpoint = "https://api.open-meteo.com/v1/forecast"
                params = {"latitude": lat, "longitude": lon, "start_date": target.isoformat(), "end_date": target.isoformat(),
                          "daily": "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_probability_max,precipitation_sum,rain_sum,showers_sum,snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max,sunrise,sunset",
                          "timezone": "auto"}
            else:
                endpoint = "https://api.open-meteo.com/v1/forecast"
                params = {"latitude": lat, "longitude": lon,
                          "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,visibility",
                          "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,rain_sum,sunrise,sunset",
                          "timezone": "auto"}
            data = _http_json(endpoint + "?" + urllib.parse.urlencode(params))
            if daily_request:
                daily = data.get("daily", {})
                if not daily.get("time"):
                    speak("A forecast is not available for that date.")
                    return True
                i = 0
                def val(key):
                    arr = daily.get(key, [])
                    return arr[i] if i < len(arr) else None
                desc = WEATHER_CODES.get(val("weather_code"), "variable conditions")
                values = {
                    "temperature": f"high {val('temperature_2m_max')}°C and low {val('temperature_2m_min')}°C",
                    "feels": f"feels-like high {val('apparent_temperature_max')}°C and low {val('apparent_temperature_min')}°C",
                    "rain": f"chance of precipitation up to {val('precipitation_probability_max')}%; expected rain {val('rain_sum')} mm; showers {val('showers_sum')} mm",
                    "humidity": "daily humidity forecast is not available from this data source",
                    "wind": f"maximum wind {val('wind_speed_10m_max')} km/h, gusts {val('wind_gusts_10m_max')} km/h",
                    "snow": f"snowfall {val('snowfall_sum')} cm",
                    "uv": f"maximum UV index {val('uv_index_max')}",
                    "sunrise": f"sunrise {val('sunrise')} and sunset {val('sunset')}",
                    "general": f"{desc}; high {val('temperature_2m_max')}°C, low {val('temperature_2m_min')}°C; precipitation chance {val('precipitation_probability_max')}%; rain {val('rain_sum')} mm; wind up to {val('wind_speed_10m_max')} km/h; UV index {val('uv_index_max')}; sunrise {val('sunrise')}; sunset {val('sunset')}"
                }
            else:
                cur = data.get("current", {})
                daily = data.get("daily", {})
                desc = WEATHER_CODES.get(cur.get("weather_code"), "conditions unavailable")
                def curval(key): return cur.get(key, "unavailable")
                def dayval(key):
                    arr = daily.get(key, [])
                    return arr[0] if arr else "unavailable"
                values = {
                    "temperature": f"{curval('temperature_2m')}°C; feels like {curval('apparent_temperature')}°C",
                    "feels": f"feels like {curval('apparent_temperature')}°C",
                    "rain": f"rain now {curval('rain')} mm; precipitation now {curval('precipitation')} mm; chance of precipitation today up to {dayval('precipitation_probability_max')}%",
                    "humidity": f"humidity {curval('relative_humidity_2m')}%",
                    "wind": f"wind {curval('wind_speed_10m')} km/h from {curval('wind_direction_10m')} degrees; gusts {curval('wind_gusts_10m')} km/h",
                    "snow": f"snowfall now {curval('snowfall')} cm",
                    "cloud": f"cloud cover {curval('cloud_cover')}%",
                    "pressure": f"pressure {curval('pressure_msl')} hectopascals",
                    "visibility": f"visibility {curval('visibility')} metres",
                    "uv": f"UV index {curval('uv_index')}",
                    "sunrise": f"sunrise {dayval('sunrise')} and sunset {dayval('sunset')}",
                    "general": f"{desc}; temperature {curval('temperature_2m')}°C, feels like {curval('apparent_temperature')}°C; humidity {curval('relative_humidity_2m')}%; cloud cover {curval('cloud_cover')}%; rain {curval('rain')} mm; wind {curval('wind_speed_10m')} km/h; pressure {curval('pressure_msl')} hPa; visibility {curval('visibility')} metres; UV index {curval('uv_index')}"
                }

        # Answer only the specific weather detail requested; otherwise give a useful summary.
        if any(x in text for x in ("temperature", "how hot", "how cold")):
            detail = values["temperature"]
        elif "feels like" in text or "feels-like" in text:
            detail = values["feels"]
        elif any(x in text for x in ("rain", "raining", "rainfall", "precipitation", "will it rain", "chance of rain")):
            detail = values["rain"]
        elif "humid" in text:
            detail = values["humidity"]
        elif any(x in text for x in ("wind", "gust")):
            detail = values["wind"]
        elif any(x in text for x in ("snow", "snowfall")):
            detail = values["snow"]
        elif "cloud" in text:
            detail = values.get("cloud", values["general"])
        elif "pressure" in text:
            detail = values.get("pressure", values["general"])
        elif "visibility" in text or "fog" in text:
            detail = values.get("visibility", values["general"])
        elif "uv" in text:
            detail = values["uv"]
        elif "sunrise" in text or "sunset" in text:
            detail = values["sunrise"]
        else:
            detail = values["general"]
        speak(f"{place_name}: {detail}.")
    except Exception as error:
        print("WEATHER LOOKUP ERROR:", repr(error))
        speak("I couldn't retrieve weather data. Please check your internet connection and try again.")
    return True

def handle_command7(command):
    """Command 7: local time, calendar dates, weather, and seasons."""
    text = (command or "").lower().strip()
    # Weather and season intent must win over calendar keywords such as "tomorrow".
    weather_intent = any(re.search(r"\b" + re.escape(word) + r"\b", text) for word in (
        "weather", "temperature", "forecast", "rain", "raining", "rainfall", "precipitation",
        "humidity", "humid", "wind", "windy", "gust", "snow", "snowfall", "cloud", "cloudy",
        "sunny", "sunshine", "uv", "visibility", "pressure", "thunderstorm", "storm", "fog",
        "season", "seasons", "summer", "winter", "spring", "autumn", "fall", "monsoon", "sunrise", "sunset"
    ))
    if weather_intent and _handle_weather(text):
        return True
    if _handle_time_calendar(text):
        return True
    return False


# ---------------------- Command 8: General Knowledge ----------------------
# Command 8 is deliberately kept self-contained so Commands 1-7 are not changed.
# Current political data below is a dated snapshot: 4 October 2026.

COUNTRY_CAPITALS = {
    "india":"New Delhi", "united states":"Washington, D.C.", "usa":"Washington, D.C.",
    "united kingdom":"London", "uk":"London", "france":"Paris", "germany":"Berlin",
    "italy":"Rome", "spain":"Madrid", "russia":"Moscow", "china":"Beijing",
    "japan":"Tokyo", "south korea":"Seoul", "north korea":"Pyongyang", "nepal":"Kathmandu",
    "bhutan":"Thimphu", "bangladesh":"Dhaka", "pakistan":"Islamabad", "sri lanka":"Sri Jayawardenepura Kotte",
    "maldives":"Male", "afghanistan":"Kabul", "iran":"Tehran", "iraq":"Baghdad",
    "saudi arabia":"Riyadh", "united arab emirates":"Abu Dhabi", "uae":"Abu Dhabi",
    "qatar":"Doha", "turkey":"Ankara", "australia":"Canberra", "new zealand":"Wellington",
    "canada":"Ottawa", "mexico":"Mexico City", "brazil":"Brasilia", "argentina":"Buenos Aires",
    "south africa":"Pretoria is the executive capital; Cape Town is the legislative capital; Bloemfontein is the judicial capital",
    "nigeria":"Abuja", "kenya":"Nairobi", "egypt":"Cairo", "ethiopia":"Addis Ababa",
    "switzerland":"Bern", "sweden":"Stockholm", "norway":"Oslo", "finland":"Helsinki",
    "denmark":"Copenhagen", "netherlands":"Amsterdam", "belgium":"Brussels", "austria":"Vienna",
    "greece":"Athens", "ireland":"Dublin", "poland":"Warsaw", "ukraine":"Kyiv",
    "thailand":"Bangkok", "vietnam":"Hanoi", "singapore":"Singapore", "indonesia":"Jakarta",
    "malaysia":"Kuala Lumpur", "philippines":"Manila", "myanmar":"Naypyidaw",
}

INDIAN_STATE_CAPITALS = {
    "andhra pradesh":"Amaravati", "arunachal pradesh":"Itanagar", "assam":"Dispur",
    "bihar":"Patna", "chhattisgarh":"Raipur", "goa":"Panaji", "gujarat":"Gandhinagar",
    "haryana":"Chandigarh", "himachal pradesh":"Shimla", "jharkhand":"Ranchi",
    "karnataka":"Bengaluru", "kerala":"Thiruvananthapuram", "madhya pradesh":"Bhopal",
    "maharashtra":"Mumbai", "manipur":"Imphal", "meghalaya":"Shillong", "mizoram":"Aizawl",
    "nagaland":"Kohima", "odisha":"Bhubaneswar", "punjab":"Chandigarh", "rajasthan":"Jaipur",
    "sikkim":"Gangtok", "tamil nadu":"Chennai", "telangana":"Hyderabad", "tripura":"Agartala",
    "uttar pradesh":"Lucknow", "uttarakhand":"Dehradun", "west bengal":"Kolkata",
}

# Snapshot verified against current sources around 4 October 2026.
INDIA_CURRENT_LEADERS = {
    "president": ("Droupadi Murmu", "She is the 15th President of India and took office on 25 July 2022."),
    "prime minister": ("Narendra Modi", "He has served as Prime Minister of India since 26 May 2014 and began his third term on 9 June 2024."),
}

STATE_CMS_2026 = {
    "andhra pradesh": ("N. Chandrababu Naidu", "Telugu Desam Party (TDP)"),
    "arunachal pradesh": ("Pema Khandu", "Bharatiya Janata Party (BJP)"),
    "assam": ("Himanta Biswa Sarma", "Bharatiya Janata Party (BJP)"),
    "bihar": ("Samrat Choudhary", "Bharatiya Janata Party (BJP)"),
    "chhattisgarh": ("Vishnu Deo Sai", "Bharatiya Janata Party (BJP)"),
    "goa": ("Pramod Sawant", "Bharatiya Janata Party (BJP)"),
    "gujarat": ("Bhupendra Patel", "Bharatiya Janata Party (BJP)"),
    "haryana": ("Nayab Singh Saini", "Bharatiya Janata Party (BJP)"),
    "himachal pradesh": ("Sukhvinder Singh Sukhu", "Indian National Congress (INC)"),
    "jharkhand": ("Hemant Soren", "Jharkhand Mukti Morcha (JMM)"),
    "karnataka": ("D. K. Shivakumar", "Indian National Congress (INC)"),
    "kerala": ("V. D. Satheesan", "United Democratic Front (UDF)"),
    "madhya pradesh": ("Mohan Yadav", "Bharatiya Janata Party (BJP)"),
    "maharashtra": ("Devendra Fadnavis", "Bharatiya Janata Party (BJP)"),
    "manipur": ("Yumnam Khemchand Singh", "Bharatiya Janata Party (BJP)"),
    "meghalaya": ("Conrad Sangma", "National People's Party (NPP)"),
    "mizoram": ("Lalduhoma", "Zoram People's Movement (ZPM)"),
    "nagaland": ("Neiphiu Rio", "Nationalist Democratic Progressive Party (NDDP) / NPF listing varies by source"),
    "odisha": ("Mohan Charan Majhi", "Bharatiya Janata Party (BJP)"),
    "punjab": ("Bhagwant Mann", "Aam Aadmi Party (AAP)"),
    "rajasthan": ("Bhajan Lal Sharma", "Bharatiya Janata Party (BJP)"),
    "sikkim": ("Prem Singh Tamang", "Sikkim Krantikari Morcha (SKM)"),
    "tamil nadu": ("C. Joseph Vijay", "Tamilaga Vettri Kazhagam (TVK)"),
    "telangana": ("Revanth Reddy", "Indian National Congress (INC)"),
    "tripura": ("Manik Saha", "Bharatiya Janata Party (BJP)"),
    "uttar pradesh": ("Yogi Adityanath", "Bharatiya Janata Party (BJP)"),
    "uttarakhand": ("Pushkar Singh Dhami", "Bharatiya Janata Party (BJP)"),
    "west bengal": ("Suvendu Adhikari", "Bharatiya Janata Party (BJP)"),
}

PERSON_FACTS = {
    "mahatma gandhi": "Mahatma Gandhi, born Mohandas Karamchand Gandhi on 2 October 1869, was a major leader of India's freedom movement. He promoted nonviolent resistance and civil disobedience, including the Non-Cooperation Movement, Salt March and Quit India Movement. He was assassinated on 30 January 1948. India observes his birthday as Gandhi Jayanti on 2 October.",
    "gandhi": "Mahatma Gandhi, born Mohandas Karamchand Gandhi on 2 October 1869, was a major leader of India's freedom movement. He promoted nonviolent resistance and civil disobedience. He was assassinated on 30 January 1948.",
    "subhas chandra bose": "Subhas Chandra Bose, popularly known as Netaji, was an Indian nationalist leader born on 23 January 1897. He led the Indian National Army and sought to end British rule in India with armed struggle. He is remembered for the slogan 'Jai Hind' and for his leadership of the INA.",
    "bhagat singh": "Bhagat Singh was an Indian revolutionary born on 28 September 1907. He became one of the most prominent young revolutionaries of the Indian independence movement and was executed by the British on 23 March 1931.",
    "sardar vallabhbhai patel": "Sardar Vallabhbhai Patel was born on 31 October 1875. He was a major leader of the freedom movement and India's first Deputy Prime Minister and Home Minister. He played a central role in integrating many princely states into the Indian Union.",
    "dr br ambedkar": "Dr. B. R. Ambedkar was born on 14 April 1891. He was a jurist, economist, social reformer and principal architect of the drafting of the Constitution of India. He served as independent India's first Law and Justice Minister.",
    "jawaharlal nehru": "Jawaharlal Nehru was born on 14 November 1889. He was a major leader of India's independence movement and became independent India's first Prime Minister, serving from 1947 until 1964. He is associated with India's early democratic and economic institution-building.",
    "sarojini naidu": "Sarojini Naidu was born on 13 February 1879. She was a poet, freedom fighter and political leader who became the first Indian woman president of the Indian National Congress and later the first woman Governor of an Indian state.",
}

GK_FACTS = {
    "india national bird": "India's national bird is the Indian peafowl, commonly called the peacock.",
    "india national animal": "India's national animal is the Bengal tiger.",
    "india national flower": "India's national flower is the lotus.",
    "india national anthem": "India's national anthem is Jana Gana Mana, written by Rabindranath Tagore.",
    "india national song": "India's national song is Vande Mataram, written by Bankim Chandra Chattopadhyay.",
    "india independence day": "India celebrates Independence Day on 15 August. India became independent from British rule on 15 August 1947.",
    "india republic day": "India celebrates Republic Day on 26 January. The Constitution of India came into effect on 26 January 1950.",
    "india constitution day": "Constitution Day is observed on 26 November, commemorating the adoption of the Constitution in 1949.",
    "india flag": "India's national flag is the Tiranga, with saffron, white and green horizontal bands and a navy-blue 24-spoke Ashoka Chakra in the centre of the white band.",
    "world war 1": "World War I lasted from 1914 to 1918. It involved the Allied Powers and the Central Powers and ended with the defeat of the Central Powers.",
    "world war 2": "World War II lasted from 1939 to 1945. It involved the Allied Powers and the Axis Powers and ended with the defeat of the Axis Powers.",
    "classical dances india": "The eight classical dance forms commonly recognised in India are Bharatanatyam, Kathak, Kathakali, Kuchipudi, Manipuri, Mohiniyattam, Odissi and Sattriya.",
    "indian cinema languages": "Indian cinema is made in many languages, including Hindi, Telugu, Tamil, Malayalam, Kannada, Bengali, Marathi, Gujarati, Punjabi, Odia, Assamese, Bhojpuri, Manipuri, Konkani and many others.",
    "transport india": "Major transportation systems in India include roads, railways, buses, metro rail, airports and airways, inland waterways, ports and shipping.",
}


def _gk_clean(text):
    """Normalize common spoken question forms for the GK handler."""
    text = normalize_command(text or "")
    text = re.sub(r"\b(sara|please|can you|could you|would you|tell me|tell us|give me|say about|explain|what is|what are|who is|who was|who's|when is|when was|where is|name of|about)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# More complete biographies: answer who/what/tell-me-about questions with a biography,
# not just a birth date. Facts are offline and can be extended without changing Commands 1-7.
PERSON_FACTS.update({
    "mahatma gandhi": "Mahatma Gandhi, whose full name was Mohandas Karamchand Gandhi, was born on 2 October 1869. He became one of the best-known leaders of India's independence movement and promoted satyagraha, non-violent resistance and civil disobedience. He led or inspired campaigns including the Non-Cooperation Movement, the Salt March and the Quit India Movement. He was assassinated on 30 January 1948. His birthday is observed in India as Gandhi Jayanti and internationally as the International Day of Non-Violence.",
    "gandhi": "Mahatma Gandhi, whose full name was Mohandas Karamchand Gandhi, was born on 2 October 1869. He was a major leader of India's independence movement and promoted non-violent resistance. He inspired the Non-Cooperation Movement, the Salt March and the Quit India Movement. He was assassinated on 30 January 1948.",
    "dr apj abdul kalam": "Dr. A. P. J. Abdul Kalam was an Indian aerospace scientist who helped develop India's space and missile programmes. Known as the Missile Man of India, he served as the 11th President of India from 2002 to 2007. He was also a teacher and author who encouraged young people to pursue science and education. He was born on 15 October 1931 and died on 27 July 2015.",
    "apj abdul kalam": "Dr. A. P. J. Abdul Kalam was an Indian aerospace scientist, a key contributor to India's space and missile programmes, and the 11th President of India from 2002 to 2007. He encouraged students to pursue science and education. He was born on 15 October 1931 and died on 27 July 2015.",
    "mother teresa": "Mother Teresa, born Anjezë Gonxhe Bojaxhiu, was a Catholic nun and humanitarian who founded the Missionaries of Charity in Kolkata in 1950. The organisation cared for people experiencing poverty and illness. She received the Nobel Peace Prize in 1979. She was born on 26 August 1910 and died on 5 September 1997.",
    "indira gandhi": "Indira Gandhi was India's first and, to date, only woman Prime Minister. She served from 1966 to 1977 and again from 1980 until her assassination in 1984. She was a major political figure during the Bangladesh Liberation War of 1971 and remains a significant and debated figure in Indian history. She was born on 19 November 1917.",
    "rani lakshmibai": "Rani Lakshmibai, the queen of Jhansi, was a leading figure in the Indian Rebellion of 1857 against British rule. She became a lasting symbol of courage and resistance. She died in battle in June 1858.",
    "chhatrapati shivaji maharaj": "Chhatrapati Shivaji Maharaj founded the Maratha kingdom in western India in the 17th century. He is remembered for his military strategy, administration and the development of a strong navy. He was crowned at Raigad in 1674.",
    "vivekananda": "Swami Vivekananda was an Indian Hindu monk and philosopher who helped introduce Indian spiritual thought to international audiences, notably at the 1893 World's Parliament of Religions in Chicago. He founded the Ramakrishna Mission with a focus on service and education. He was born on 12 January 1863.",
    "swami vivekananda": "Swami Vivekananda was an Indian Hindu monk and philosopher who represented Hinduism at the 1893 World's Parliament of Religions in Chicago. He founded the Ramakrishna Mission and inspired many people through his teachings on service, education and self-confidence. He was born on 12 January 1863.",
    "sardar patel": "Sardar Vallabhbhai Patel was a leading figure in India's independence movement and independent India's first Deputy Prime Minister and Home Minister. He played a central role in integrating many princely states into the Indian Union after independence. He was born on 31 October 1875 and is widely known as the Iron Man of India.",
})


def handle_command8(command):
    """General knowledge handler. Called before the generic chat fallback."""
    raw = normalize_command(command or "")
    text = _gk_clean(raw)
    if not raw:
        return False

    # Robust aliases for five reported failures. These run first and accept common
    # ASR variants (singular/plural, missing words, and reordered question phrases).
    compact = re.sub(r"[^a-z0-9 ]", " ", raw)
    compact = re.sub(r"\s+", " ", compact).strip()
    compact_words = set(compact.split())

    if ("actress" in compact_words or "actresses" in compact_words) and (
        "indian" in compact_words or "india" in compact_words or "famous" in compact_words
    ):
        speak("Some famous Indian actresses include Sridevi, Madhuri Dixit, Aishwarya Rai Bachchan, Deepika Padukone, Priyanka Chopra Jonas, Nayanthara, Sai Pallavi and Alia Bhatt.")
        return True

    if "automobile" in compact_words and (
        "company" in compact_words or "companies" in compact_words or "indian" in compact_words
    ) and ("indian" in compact_words or "india" in compact_words):
        speak("Major Indian automobile companies include Tata Motors, Mahindra and Mahindra, Maruti Suzuki, Ashok Leyland, Bajaj Auto and TVS Motor.")
        return True

    if ("automobile" in compact_words or "car" in compact_words or "cars" in compact_words) and (
        "brand" in compact_words or "brands" in compact_words or "famous" in compact_words
    ):
        speak("Famous automobile brands include Toyota, Honda, Hyundai, Ford, Volkswagen, BMW, Mercedes-Benz, Tata Motors and Mahindra.")
        return True

    if ("electronics" in compact_words or ("electronic" in compact_words and "brand" in compact_words)) and (
        "brand" in compact_words or "brands" in compact_words or "popular" in compact_words
    ):
        speak("Popular electronics brands include Samsung, Sony, LG, Panasonic, Philips, Dell, HP and Lenovo.")
        return True

    if "festival" in compact_words or "festivals" in compact_words:
        if "india" in compact_words or "indian" in compact_words or "major" in compact_words or "celebrated" in compact_words:
            speak("Major festivals celebrated in India include Diwali, Holi, Dussehra, Eid, Christmas, Gurpurab, Navratri, Ganesh Chaturthi, Onam, Pongal and Sankranti.")
            return True

    # Short, direct answers for the requested offline GK questions. These rules run
    # before broad biography/topic matching so Sara answers the exact thing asked.
    q = re.sub(r"\b(sara|please|tell me|tell us|can you|could you|what is|what are|who is|who was|when is|when was|name some|name the|name|list|give me|about|in india|of india)\b", " ", raw)
    q = re.sub(r"\s+", " ", q).strip()
    direct_facts = [
        (("national tree" in raw), "India's national tree is the Indian banyan tree."),
        (("how many states" in raw or "number of states" in raw) and "india" in raw or raw in {"how many states", "how many states does india have"}, "India has 28 states."),
        (("union territories" in raw or "union territory" in raw) and ("how many" in raw or "number" in raw or raw.startswith("union territories")), "India has 8 Union Territories."),
        (("currency" in raw and ("india" in raw or "indian" in raw or raw == "currency")), "India's currency is the Indian rupee, written as INR and symbolised by ₹."),
        (("became independent" in raw or "independent" in raw and "india" in raw and ("when" in raw or "date" in raw)), "India became independent from British rule on 15 August 1947."),
        (("kargil vijay diwas" in raw), "Kargil Vijay Diwas is observed on 26 July every year, remembering India's victory in the 1999 Kargil War and honouring its fallen soldiers."),
        (("born" in raw and ("gandhi" in raw or "mahatma gandhi" in raw)), "Mahatma Gandhi was born on 2 October 1869."),
        (("born" in raw and ("abdul kalam" in raw or "apj" in raw)), "Dr. A. P. J. Abdul Kalam was born on 15 October 1931."),
        (("south india" in raw and ("states" in raw or "name" in raw or "which" in raw)), "The five commonly listed South Indian states are Andhra Pradesh, Karnataka, Kerala, Tamil Nadu and Telangana."),
        (("party" in raw and ("andhra pradesh" in raw or "andhra" in raw)), "As of this offline knowledge snapshot, Andhra Pradesh is governed by the Telugu Desam Party-led coalition, with N. Chandrababu Naidu as Chief Minister. Political details can change."),
        (("governor" in raw and ("andhra pradesh" in raw or "andhra" in raw)), "Sara's offline data may not reflect the latest Governor appointment. Please verify the current Governor of Andhra Pradesh from the official Raj Bhavan or state government website."),
        (("major festivals" in raw or "festivals celebrated in india" in raw), "Major festivals celebrated in India include Diwali, Holi, Dussehra, Eid, Christmas, Gurpurab, Navratri, Ganesh Chaturthi, Onam, Pongal and Sankranti."),
        (("diwali" in raw), "Diwali, the festival of lights, usually falls in October or November, on the Hindu lunisolar calendar's Amavasya in the month of Kartika. The exact date changes each year."),
        (("sankranti" in raw or "makar sankranti" in raw), "Sankranti, commonly Makar Sankranti in many regions, is a harvest festival marking the Sun's transition into Capricorn. It is usually celebrated around 14 January, with regional customs including kite flying, special foods and gratitude for the harvest."),
        (("ugadi" in raw), "Ugadi is the Telugu and Kannada New Year festival, usually celebrated in March or April. Families prepare Ugadi pachadi in Andhra Pradesh and Telangana, symbolising the different experiences of life."),
        (("pongal" in raw), "Pongal is a Tamil harvest festival celebrated over several days in January. People cook the Pongal dish, thank the Sun and cattle, and celebrate the harvest."),
        (("onam" in raw), "Onam is Kerala's major harvest festival, usually celebrated in August or September. It features pookalam flower designs, Onam sadhya, boat races and traditions associated with King Mahabali."),
        (("ganesh chaturthi" in raw), "Ganesh Chaturthi celebrates the birth of Lord Ganesha. It usually falls in August or September, with prayers, decorated idols and community celebrations."),
        (("kuchipudi" in raw), "Kuchipudi is a classical Indian dance form that originated in Andhra Pradesh. It combines expressive storytelling, rhythmic footwork, music and dramatic performance."),
        (("bharatanatyam" in raw), "Bharatanatyam is a classical Indian dance form originating in Tamil Nadu, known for expressive gestures, precise footwork, rhythmic patterns and storytelling."),
        (("andhra pradesh culture" in raw or "culture of andhra pradesh" in raw), "Andhra Pradesh culture includes Telugu language and literature, Kuchipudi dance, Carnatic music, handloom traditions, regional cuisine and festivals such as Sankranti and Ugadi."),
        (("festivals" in raw and "telangana" in raw), "Festivals celebrated in Telangana include Bathukamma, Bonalu, Sankranti, Ugadi, Dasara, Diwali and Ramzan/Eid."),
        (("classical dance" in raw), "The eight classical dance forms commonly recognised in India are Bharatanatyam, Kathak, Kathakali, Kuchipudi, Manipuri, Mohiniyattam, Odissi and Sattriya."),
        (("largest ocean" in raw), "The Pacific Ocean is the largest ocean on Earth."),
        (("highest mountain" in raw), "Mount Everest, in the Himalayas on the Nepal–China border, is the world's highest mountain above sea level."),
        (("continents" in raw and ("how many" in raw or "name" in raw)), "There are seven continents: Africa, Antarctica, Asia, Europe, North America, South America and Australia (often grouped as Oceania)."),
        (("planets" in raw and ("solar system" in raw or "name" in raw)), "The eight planets in order from the Sun are Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus and Neptune."),
        (("smallest country" in raw), "Vatican City is the world's smallest independent country by area."),
        (("largest population" in raw or "most populous country" in raw), "India is the world's most populous country according to recent United Nations estimates."),
        (("automobile brands" in raw), "Famous automobile brands include Toyota, Honda, Hyundai, Ford, Volkswagen, BMW, Mercedes-Benz, Tata Motors and Mahindra."),
        (("electronics brands" in raw), "Popular electronics brands include Samsung, Sony, LG, Panasonic, Philips, Dell, HP and Lenovo."),
        (("clothing brands" in raw), "Popular clothing brands include Nike, Adidas, Puma, Levi's, H&M, Zara, Uniqlo and FabIndia."),
        (("smartphone brands" in raw), "Popular smartphone brands include Apple, Samsung, Xiaomi, OnePlus, Vivo, Oppo, Motorola and Google Pixel."),
        (("types of transportation" in raw or "different types of transportation" in raw), "The main types of transportation are road, rail, air and water transport. Pipelines are also used to transport liquids and gases."),
        (("indian automobile companies" in raw or "indian automobile company" in raw), "Major Indian automobile manufacturers include Tata Motors, Mahindra & Mahindra, Maruti Suzuki India, Ashok Leyland, Bajaj Auto and TVS Motor."),
        (("electric vehicles" in raw), "Electric vehicles use electric motors and batteries instead of, or alongside, petrol or diesel engines. They can reduce tailpipe emissions and running costs, but charging access, battery cost and electricity sources matter."),
        (("fastest mode of transport" in raw), "For long-distance passenger travel on Earth, commercial airplanes are generally the fastest widely available mode of transport."),
        (("telugu cinema" in raw), "Telugu cinema, often called Tollywood, is a major Indian film industry centred mainly in Hyderabad and known for films made in Telugu."),
        (("tamil cinema" in raw), "Tamil cinema, often called Kollywood, is the Tamil-language film industry, centred mainly in Chennai."),
        (("malayalam cinema" in raw), "Malayalam cinema is the Malayalam-language film industry, based mainly in Kerala and known for a strong tradition of character-driven storytelling."),
        (("kannada cinema" in raw), "Kannada cinema, also called Sandalwood, is the Kannada-language film industry, based mainly in Karnataka."),
        (("hindi cinema" in raw), "Hindi cinema is a major Indian film industry associated especially with Mumbai and often popularly called Bollywood."),
        (("famous telugu actors" in raw or "telugu actors" in raw), "Some famous Telugu actors include Chiranjeevi, Nagarjuna, Venkatesh, Pawan Kalyan, Mahesh Babu, Allu Arjun, Prabhas, Jr. NTR and Ram Charan."),
        (("indian actresses" in raw or "famous indian actresses" in raw), "Some famous Indian actresses include Sridevi, Madhuri Dixit, Aishwarya Rai Bachchan, Deepika Padukone, Priyanka Chopra Jonas, Nayanthara, Sai Pallavi and Alia Bhatt."),
        (("major film industries" in raw or "film industries in india" in raw or "indian film industries" in raw), "Major Indian film industries include Hindi, Telugu, Tamil, Malayalam, Kannada, Bengali, Marathi, Punjabi, Gujarati, Odia and Assamese cinema."),
        (("scheduled languages" in raw), "India has 22 languages listed in the Eighth Schedule of its Constitution."),
        (("film industries" in raw and ("languages" in raw or "different language" in raw)), "Indian films are made in many languages, including Hindi, Telugu, Tamil, Malayalam, Kannada, Bengali, Marathi, Gujarati, Punjabi, Odia and Assamese."),
    ]
    for matched, answer in direct_facts:
        if matched:
            speak(answer)
            return True

    # Explicit biography answers for two commonly phrased questions.
    if "rani lakshmibai" in raw and ("who was" in raw or "tell me" in raw or "about" in raw):
        speak("Rani Lakshmibai was the queen of Jhansi and a prominent leader in the Indian Rebellion of 1857 against British rule. She became a symbol of courage and resistance and died fighting in June 1858.")
        return True
    if "swami vivekananda" in raw and ("tell me" in raw or "about" in raw or "who was" in raw):
        speak("Swami Vivekananda was an Indian monk and philosopher, born on 12 January 1863. He introduced Indian spiritual ideas to international audiences at the 1893 Parliament of the World's Religions in Chicago and helped establish the Ramakrishna Mission, which supports education and service.")
        return True

    # Match birth-date questions with a short date-only response, not a full biography.
    if "born" in raw and any(name in raw for name in ("sarojini naidu", "rani lakshmibai", "swami vivekananda")):
        birth_dates = {
            "sarojini naidu": "Sarojini Naidu was born on 13 February 1879.",
            "rani lakshmibai": "Rani Lakshmibai was born on 19 November 1828 (the commonly cited date).",
            "swami vivekananda": "Swami Vivekananda was born on 12 January 1863.",
        }
        for name, answer in birth_dates.items():
            if name in raw:
                speak(answer)
                return True

    # 1) Person biographies. Match longer names first and tolerate question prefixes.
    person_aliases = {
        "mahatma gandhi": ("mahatma gandhi", "gandhi"),
        "mohandas karamchand gandhi": ("mahatma gandhi", "gandhi"),
        "gandhi": ("gandhi",),
        "subhas chandra bose": ("subhas chandra bose", "netaji"),
        "netaji": ("subhas chandra bose", "netaji"),
        "bhagat singh": ("bhagat singh",),
        "sardar vallabhbhai patel": ("sardar vallabhbhai patel", "sardar patel"),
        "sardar patel": ("sardar patel", "sardar vallabhbhai patel"),
        "dr br ambedkar": ("dr br ambedkar", "ambedkar"),
        "br ambedkar": ("dr br ambedkar", "ambedkar"),
        "ambedkar": ("dr br ambedkar", "ambedkar"),
        "jawaharlal nehru": ("jawaharlal nehru",),
        "sarojini naidu": ("sarojini naidu",),
        "apj abdul kalam": ("dr apj abdul kalam", "apj abdul kalam"),
        "a p j abdul kalam": ("dr apj abdul kalam", "apj abdul kalam"),
        "abdul kalam": ("dr apj abdul kalam", "apj abdul kalam"),
        "mother teresa": ("mother teresa",),
        "indira gandhi": ("indira gandhi",),
        "rani lakshmibai": ("rani lakshmibai",),
        "chhatrapati shivaji maharaj": ("chhatrapati shivaji maharaj",),
        "swami vivekananda": ("swami vivekananda", "vivekananda"),
        "vivekananda": ("swami vivekananda", "vivekananda"),
    }
    for alias in sorted(person_aliases, key=len, reverse=True):
        if re.search(r"\b" + re.escape(alias) + r"\b", raw):
            for fact_key in person_aliases[alias]:
                if fact_key in PERSON_FACTS:
                    speak(PERSON_FACTS[fact_key])
                    return True

    # 2) National leaders: handle both explicit country and common short forms.
    if ("president" in raw and ("india" in raw or raw in {"who is the president", "who is president", "president", "current president"})):
        name, detail = INDIA_CURRENT_LEADERS["president"]
        speak(f"The current President of India is {name}. {detail}")
        return True
    if ("prime minister" in raw or re.search(r"\bpm\b", raw)) and ("india" in raw or raw in {"who is the prime minister", "who is prime minister", "prime minister", "current prime minister", "pm"}):
        name, detail = INDIA_CURRENT_LEADERS["prime minister"]
        speak(f"The current Prime Minister of India is {name}. {detail}")
        return True
    if "chief minister" in raw or re.search(r"\bcm\b", raw):
        if "india" in raw and not any(state in raw for state in STATE_CMS_2026):
            speak("India does not have a Chief Minister. India has a Prime Minister at the national level, and each state has its own Chief Minister.")
            return True
        for state, (name, party) in sorted(STATE_CMS_2026.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"\b" + re.escape(state) + r"\b", raw):
                speak(f"The stored Command 8 snapshot lists {name} as Chief Minister of {state.title()}, with {party}. Political offices can change, so verify current officeholders with the official India government directory.")
                return True
        if "chief minister" in raw or re.search(r"\bcm\b", raw):
            speak("Which Indian state do you mean? For example, ask: Who is the Chief Minister of Andhra Pradesh?")
            return True

    # 3) Capital questions: state and country name can appear in any order.
    if "capital" in raw:
        for state, capital in sorted(INDIAN_STATE_CAPITALS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"\b" + re.escape(state) + r"\b", raw):
                speak(f"The capital of {state.title()} is {capital}.")
                return True
        for country, capital in sorted(COUNTRY_CAPITALS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"\b" + re.escape(country) + r"\b", raw):
                speak(f"The capital of {country.title()} is {capital}.")
                return True
        if raw in {"what is the capital", "capital", "what is capital"}:
            speak("Which country or Indian state would you like the capital of?")
            return True

    # 4) Common facts and history. Match by topic keywords, not exact sentence only.
    fact_patterns = [
        (("national bird" in raw) and ("india" in raw or "indian" in raw or raw in {"national bird", "what is the national bird"}), "india national bird"),
        (("national animal" in raw) and ("india" in raw or "indian" in raw or raw in {"national animal", "what is the national animal"}), "india national animal"),
        (("national flower" in raw), "india national flower"),
        (("national anthem" in raw), "india national anthem"),
        (("national song" in raw), "india national song"),
        (("flag" in raw and ("india" in raw or "indian" in raw or "tiranga" in raw)), "india flag"),
        (("independence day" in raw and ("india" in raw or "indian" in raw or raw in {"independence day", "when is independence day"})), "india independence day"),
        (("republic day" in raw), "india republic day"),
        (("constitution day" in raw), "india constitution day"),
        (("world war 1" in raw or "world war one" in raw or "first world war" in raw or "world war i" in raw), "world war 1"),
        (("world war 2" in raw or "world war two" in raw or "second world war" in raw or "world war ii" in raw), "world war 2"),
        (("classical dance" in raw or "classical dances" in raw) and "india" in raw, "classical dances india"),
        (("indian film languages" in raw or "languages of indian movies" in raw or "languages are indian movies" in raw or "indian cinema languages" in raw), "indian cinema languages"),
        (("transport" in raw or "transportation" in raw) and ("india" in raw or "indian" in raw), "transport india"),
    ]
    for matched, key in fact_patterns:
        if matched and key in GK_FACTS:
            speak(GK_FACTS[key])
            return True

    # 5) Indian population: clearly label the answer as an estimate, not a census count.
    if "population" in raw and ("india" in raw or "indian" in raw):
        speak("India's population is estimated at around 1.4 billion people. The exact number depends on the source and date; India's last completed national census was in 2011, so current figures are estimates rather than a new census count.")
        return True

    # 6) General topic routing with a helpful prompt rather than an unrelated answer.
    topic_words = (
        "population", "president", "prime minister", "chief minister", "capital", "national bird", "national animal",
        "flag", "world war", "freedom fighter", "freedom fighters", "festival", "classical dance", "culture", "district",
        "movie", "movies", "film", "cinema", "transport", "transportation", "brand", "electronics", "automobile",
        "smart device", "country", "state", "prime minister", "population"
    )
    if any(word in raw for word in topic_words):
        speak("I recognised your General Knowledge question, but this exact fact is not in Sara's offline database yet. Try asking about a specific country, Indian state, freedom fighter, national symbol, or World War.")
        return True
    return False


# ---------------------- Command 9: Offline AI Knowledge Center ----------------------
# Self-contained offline answers. This handler runs before Command 8 so AI questions
# are not swallowed by the general-knowledge fallback. Commands 1-8 remain unchanged.
def handle_command9(command):
    """Command 9: comprehensive offline AI knowledge center.

    This handler intentionally uses a built-in knowledge base.  It also makes
    speech-recognition output such as "I" mean "AI" only when the surrounding
    words clearly indicate an AI question; it never globally replaces every
    spoken "I" in normal conversation.
    """
    raw = normalize_command(command or "")
    if not raw:
        return False

    cleaned = re.sub(r"[^a-z0-9 ]", " ", raw.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Common speech-recognition variants for Artificial Intelligence.
    # "artifical" is a frequent spelling/transcription variant.
    cleaned = re.sub(r"\bartifical\b", "artificial", cleaned)
    cleaned = re.sub(r"\bartificial intellegence\b", "artificial intelligence", cleaned)
    cleaned = re.sub(r"\bartificial inteligence\b", "artificial intelligence", cleaned)
    # Keep the phrase "artificial intelligence" intact so both spellings
    # can match the same knowledge rules.  The AI detector below treats them
    # as equivalent without destroying the original wording.

    # Google Speech Recognition can transcribe spoken "A I" as "a i" or
    # occasionally as just "i".  Only interpret a standalone/nearby "i" as
    # AI when the question contains strong AI-topic words.
    ai_context_words = {
        "prompt", "prompts", "prompting", "engineer", "engineering",
        "chatbot", "chatbots", "robotics", "robot", "robots", "automobile",
        "automobiles", "car", "cars", "vehicle", "vehicles", "machine",
        "learning", "data", "science", "neural", "deep", "model", "models",
        "generative", "career", "careers", "roadmap", "tools", "programs",
        "programming", "applications", "websites", "students", "education",
        "creator", "creators", "artificial", "intelligence", "llm", "llms",
        "technology", "develop", "build", "building", "developing"
    }
    tokens = cleaned.split()
    if "ai" not in tokens and "artificial" not in tokens and "intelligence" not in tokens:
        if "i" in tokens and any(t in ai_context_words for t in tokens):
            # Replace only the likely AI token.  This preserves ordinary
            # sentences such as "I like music".
            for idx, token in enumerate(tokens):
                if token == "i":
                    tokens[idx] = "ai"
                    break
            cleaned = " ".join(tokens)

    # Natural variants such as "A I", "A.I.", "AI", and "artificial intelligence"
    # all arrive here as the same concept.
    has_ai = (
        "ai" in cleaned.split()
        or "artificial intelligence" in cleaned
        or "prompt engineer" in cleaned
        or "prompt engineering" in cleaned
        or "machine learning" in cleaned
        or "data science" in cleaned
        or "generative ai" in cleaned
        or "chatbot" in cleaned
        or "chatbots" in cleaned
        or "robotics" in cleaned
        or (" i " in f" {cleaned} " and any(word in cleaned.split() for word in ("full", "form", "stand", "stands", "prompt", "engineer", "roadmap", "programs", "tools", "applications", "websites", "automobiles", "chatbots")))
    )
    if not has_ai:
        return False

    answers = [
        # -------------------------------------------------------------
        # 1. Programs used to develop AI
        # -------------------------------------------------------------
        ((
            "which programs are used to develop ai",
            "what programs are used to develop ai",
            "programs used to develop ai",
            "program used to develop ai",
            "which software is used to develop ai",
            "software used to develop ai",
            "programs used in ai development",
            "which programs are used in ai",
            "what programs are used in ai",
            "programs used in ai",
            "program used to develop artificial intelligence",
        ),
         "Common programs and development environments for AI include Visual Studio Code and PyCharm for coding, Jupyter Notebook for experiments, Google Colab for cloud notebooks, and Anaconda for managing Python environments. Common AI libraries and frameworks include NumPy, pandas, scikit-learn, PyTorch, TensorFlow, Keras, Hugging Face Transformers, and OpenCV. Git is commonly used for version control. The exact tools depend on the AI project."),

        # -------------------------------------------------------------
        # 2. Tools for AI chatbots
        # -------------------------------------------------------------
        ((
            "which tools are used to build ai chatbots",
            "what tools are used to build ai chatbots",
            "tools used to build ai chatbots",
            "tools for ai chatbots",
            "tools used to build chatbots",
            "how to build an ai chatbot",
            "how to make an ai chatbot",
            "chatbot development tools",
            "ai chatbot tools",
        ),
         "AI chatbots can be built with Python or JavaScript or TypeScript, a language model or other NLP model, an application framework, an API or local model, a database when memory is needed, and a web or mobile interface. Common tools include Python, FastAPI or Flask, Node.js, React, databases such as PostgreSQL or SQLite, Hugging Face Transformers, PyTorch, TensorFlow, and vector databases for retrieval-based systems. A chatbot can also use speech recognition and text-to-speech for voice interaction. Cloud AI APIs need internet access; local models can run offline if installed and supported by the computer."),

        # -------------------------------------------------------------
        # 3. AI applications
        # -------------------------------------------------------------
        ((
            "what types of applications can we develop by using ai",
            "which types of applications can we develop using ai",
            "what type of applications can we develop using ai",
            "types of applications can develop using ai",
            "applications can develop using ai",
            "applications using ai",
            "apps using ai",
            "what applications can be developed with ai",
        ),
         "AI can be used to develop voice assistants, chatbots, tutoring apps, language translators, recommendation systems, image and speech recognition apps, document-analysis tools, accessibility applications, fraud and anomaly detection systems, predictive-maintenance apps, smart agriculture systems, healthcare-support software, finance-support tools, robotics software, autonomous-driving support systems, search tools, and creative applications for text, images, audio, and video. High-impact applications need strong testing, privacy protection, and human oversight."),

        # -------------------------------------------------------------
        # 4. AI websites
        # -------------------------------------------------------------
        ((
            "what types of websites can we develop by using ai",
            "which types of websites can we develop using ai",
            "what type of websites can we develop using ai",
            "types of websites can develop using ai",
            "websites can develop using ai",
            "websites using ai",
            "what websites can be developed with ai",
            "ai powered websites",
            "ai website ideas",
        ),
         "AI can be used in educational websites, AI tutoring sites, customer-support chatbot sites, question-answering and search sites, recommendation websites, document summarization sites, translation websites, image-analysis sites, content-generation platforms, coding assistants, accessibility websites, business analytics dashboards, recruitment-support tools, e-commerce personalization, and creative platforms. A typical AI website uses HTML, CSS and JavaScript or a web framework for the interface, a server such as Python or Node.js, and an AI model or AI service behind it."),

        # -------------------------------------------------------------
        # 5. AI automobiles
        # -------------------------------------------------------------
        ((
            "tell me about ai automobiles",
            "tell me about ai in automobiles",
            "about ai automobiles",
            "ai automobiles",
            "artificial intelligence automobiles",
            "ai in cars",
            "ai in vehicles",
            "how ai is used in automobiles",
            "how ai helps automobiles",
            "ai automobile technology",
        ),
         "AI in automobiles can support advanced driver-assistance systems, object and pedestrian detection, lane and road recognition, driver monitoring, adaptive features, parking assistance, navigation and route prediction, voice assistants, predictive maintenance, battery and energy optimization in some vehicles, and research into autonomous driving. Cameras, radar, lidar, GPS, vehicle sensors and control systems can provide data for these functions. AI systems can make mistakes, so safety engineering, testing, human supervision and applicable laws remain important."),

        # -------------------------------------------------------------
        # 6. AI career options
        # -------------------------------------------------------------
        ((
            "what are the career options for ai students",
            "career options for ai students",
            "careers for ai students",
            "career options in ai",
            "careers in ai",
            "jobs in ai",
            "ai career options",
            "what jobs can ai students do",
        ),
         "AI students can pursue careers such as AI engineer, machine-learning engineer, data scientist, data engineer, computer-vision engineer, natural-language-processing engineer, generative-AI application developer, robotics engineer, MLOps engineer, AI research scientist, AI product manager, AI solutions architect, AI safety or responsible-AI specialist, and AI software developer. A strong foundation in Python, mathematics, statistics, data structures, databases, machine learning, software engineering and projects is useful. Career requirements vary by role and employer."),

        # -------------------------------------------------------------
        # 7. AI engineer roadmap
        # -------------------------------------------------------------
        ((
            "give me a road map to become an ai engineer",
            "give me a roadmap to become an ai engineer",
            "roadmap to become an ai engineer",
            "road map to become an ai engineer",
            "how to become an ai engineer",
            "steps to become an ai engineer",
            "ai engineer roadmap",
        ),
         "A practical AI-engineer roadmap is: 1) learn Python and programming fundamentals; 2) learn data structures, algorithms, Git and basic software engineering; 3) learn mathematics including linear algebra, probability and statistics; 4) learn NumPy, pandas and data visualization; 5) learn machine learning with scikit-learn; 6) learn deep learning with PyTorch or TensorFlow; 7) study NLP, computer vision and generative AI; 8) learn APIs, databases, testing and deployment; 9) learn Docker and basic cloud or local model deployment; 10) build real projects such as a chatbot, recommendation system, vision project or voice assistant; and 11) create a portfolio and continue learning responsible AI, evaluation and security."),

        # -------------------------------------------------------------
        # 8-16 Prompt engineering
        # -------------------------------------------------------------
        ((
            "what is prompt engineer",
            "what is a prompt engineer",
            "what is prompt engineering",
            "define prompt engineer",
            "meaning of prompt engineer",
        ),
         "A prompt engineer designs, tests and improves instructions or prompts used with AI models to obtain useful, reliable and appropriately formatted results. The work can involve understanding the task, defining the desired output, adding relevant context, giving examples when useful, testing different prompts, and evaluating the results."),

        ((
            "what can do prompt engineer",
            "what does a prompt engineer do",
            "what can a prompt engineer do",
            "work of prompt engineer",
            "role of prompt engineer",
        ),
         "A prompt engineer can design prompts, create reusable prompt templates, test model behavior, improve output quality, structure responses, create evaluation cases, reduce ambiguity, add examples and constraints, and work with developers or domain experts to integrate AI into applications. In many modern teams, prompt engineering is combined with software, data, product, evaluation or AI-application work."),

        ((
            "how to become prompt engineer",
            "how can i become prompt engineer",
            "steps to become prompt engineer",
            "become a prompt engineer",
        ),
         "To become a prompt engineer, first learn how generative AI and language models work at a practical level. Then practise writing clear instructions, role and context definitions, examples, output formats and constraints. Learn Python and basic APIs so you can automate prompt tests. Study evaluation, hallucination reduction, retrieval-augmented generation, structured outputs and responsible AI. Build projects, compare prompts systematically, document results, and develop domain knowledge in an area such as education, software, business or content creation."),

        ((
            "uses of prompt engineer",
            "uses of prompt engineering",
            "why prompt engineering is used",
            "use of prompt engineer",
            "what is prompt engineering used for",
        ),
         "Prompt engineering is used to make AI interactions more consistent and useful. Examples include generating structured reports, extracting information from documents, classifying text, creating coding assistance, building customer-support workflows, tutoring, summarizing information, transforming text between formats, generating content, and controlling the style or structure of model outputs. Prompts should be evaluated rather than assumed to be reliable."),

        ((
            "examples of prompt engineer",
            "examples of prompt engineering",
            "prompt engineer examples",
            "example of prompt engineering",
        ),
         "Examples include designing a customer-support prompt that returns a fixed JSON format, creating a tutoring prompt that explains a topic step by step, building a document-extraction prompt that identifies names and dates, designing a coding prompt with tests and constraints, and creating a content prompt with a specified audience, tone and length. A prompt engineer tests these prompts against many examples and improves them from measured results."),

        ((
            "which languages programs are used to prompt engineer",
            "which programming languages are used for prompt engineering",
            "programming languages for prompt engineering",
            "language used for prompt engineering",
            "what programming language for prompt engineer",
        ),
         "Prompt engineering itself can be done without programming, because writing and testing prompts is the core skill. For automated or production prompt engineering, Python is especially useful because of its AI and data ecosystem. JavaScript or TypeScript is also widely useful for web applications. Other languages can call AI APIs as well. Helpful skills include JSON, APIs, Git, basic databases, testing and data handling."),

        ((
            "how can learn prompt engineering",
            "how to learn prompt engineering",
            "learn prompt engineering",
            "learn prompt engineer",
        ),
         "To learn prompt engineering: start with clear instructions and precise goals; practise adding context and constraints; learn examples and few-shot prompting; practise structured outputs such as JSON; test the same prompt on many inputs; measure accuracy and consistency; learn retrieval-augmented generation and tool calling; learn basic Python and APIs; study model limitations and hallucinations; and build small projects such as a study assistant or document extractor."),

        ((
            "give me a road map to become an prompt engineer",
            "give me a roadmap to become an prompt engineer",
            "roadmap to become a prompt engineer",
            "road map to become a prompt engineer",
            "prompt engineer roadmap",
        ),
         "A prompt-engineering roadmap is: 1) understand generative AI and language-model basics; 2) learn prompt structure, context, constraints and examples; 3) practise zero-shot and few-shot prompting; 4) learn structured outputs such as JSON; 5) learn evaluation and test sets; 6) learn Python, APIs and Git; 7) learn embeddings, retrieval-augmented generation and tool calling; 8) study safety, privacy and prompt-injection risks; 9) build projects and compare results; and 10) create a portfolio showing prompts, test cases, metrics and improvements."),

        ((
            "tools of prompt engineer",
            "tools used by prompt engineer",
            "prompt engineering tools",
            "tools for prompt engineering",
            "prompt engineer tools",
        ),
         "Prompt-engineering tools can include AI model interfaces, API clients, Python, Jupyter Notebook, Visual Studio Code, Git, JSON tools, evaluation frameworks, logging and experiment-tracking systems, retrieval databases, and application frameworks. Examples of model platforms include OpenAI, Google Gemini and Anthropic Claude, while local models can be tested with suitable local runtimes. Tool availability and features change over time."),

        # -------------------------------------------------------------
        # 17. Data science in AI
        # -------------------------------------------------------------
        ((
            "how can data science uses in ai",
            "how does data science use in ai",
            "how data science is used in ai",
            "how data science helps ai",
            "data science uses in ai",
            "data science in ai",
        ),
         "Data science supports AI by collecting and cleaning data, exploring patterns, selecting useful features, creating training and test datasets, analysing model performance, and communicating results. Data scientists use statistics, Python, SQL, pandas, NumPy and visualization tools. High-quality, representative data is important because poor or biased data can lead to poor or biased AI results."),

        # -------------------------------------------------------------
        # 18. Machine learning in AI
        # -------------------------------------------------------------
        ((
            "how can machine learning uses in ai",
            "how is machine learning used in ai",
            "how machine learning is used in ai",
            "how machine learning helps ai",
            "machine learning uses in ai",
            "machine learning in ai",
        ),
         "Machine learning is one of the main approaches used to build AI systems. A machine-learning model learns patterns from data and can then make predictions, classifications, recommendations or other outputs. Examples include spam detection, image classification, speech recognition, recommendation systems, forecasting and parts of autonomous systems. Common types include supervised learning, unsupervised learning and reinforcement learning."),

        # -------------------------------------------------------------
        # 19. AI for ordinary people
        # -------------------------------------------------------------
        ((
            "how can ai helps ordinary people",
            "how can ai help ordinary people",
            "how ai helps ordinary people",
            "how ai can help ordinary people",
            "ai help everyday people",
            "ai helps everyday people",
            "ai for ordinary people",
            "ai for everyday people",
        ),
         "AI can help ordinary people explain difficult topics, translate languages, write or improve messages, organize schedules, create study materials, summarize documents, brainstorm ideas, assist with accessibility, help troubleshoot everyday technology, plan tasks, and support creative work. People should protect private information, verify important answers, and avoid relying on AI alone for medical, legal, financial or other high-impact decisions."),

        # -------------------------------------------------------------
        # 20. More information about AI
        # -------------------------------------------------------------
        ((
            "tell me more about the artificial intelligence",
            "tell me more about artificial intelligence",
            "tell me more about ai",
            "more information about artificial intelligence",
            "more information about ai",
            "about artificial intelligence",
            "about ai",
            "information about ai",
            "explain artificial intelligence",
            "explain ai",
        ),
         "Artificial Intelligence is a broad field of computer science focused on building systems that can perform tasks associated with capabilities such as perception, language understanding, learning, prediction, reasoning, planning and generation. Major areas include machine learning, deep learning, natural-language processing, computer vision, speech technology, robotics, generative AI and expert systems. AI is used in education, healthcare, transport, finance, agriculture, science, accessibility, business and creative work. Good AI development requires quality data, testing, security, privacy, fairness and human oversight."),

        # -------------------------------------------------------------
        # 21. AI full form — deliberately very explicit
        # -------------------------------------------------------------
        ((
            "what is ai stands for",
            "what does ai stand for",
            "what is ai full form",
            "what is the full form of ai",
            "ai full form",
            "full form ai",
            "stand for ai",
            "stands for ai",
            "ai means",
        ),
         "AI stands for Artificial Intelligence."),

        # -------------------------------------------------------------
        # Existing core AI topics
        # -------------------------------------------------------------
        ((
            "what is ai",
            "what is artificial intelligence",
            "define ai",
            "meaning of ai",
        ),
         "AI stands for Artificial Intelligence. It is a field of computer science that develops systems capable of tasks such as understanding language, recognizing patterns, processing images and speech, making predictions, solving problems, learning from data, and generating content."),

        ((
            "how ai works",
            "how does ai work",
            "working of ai",
            "how artificial intelligence works",
        ),
         "AI systems combine data, algorithms and models to produce outputs. In machine learning, a model is trained using examples, evaluated on data it has not seen during training, and improved through an appropriate training process. A deployed model then uses learned patterns to make predictions or generate outputs. The quality of an AI system depends on data, model design, instructions, evaluation, security and the way people use it."),

        ((
            "what can ai do",
            "what can ai do for us",
            "capabilities of ai",
            "uses of ai",
            "use of ai",
            "applications of ai",
        ),
         "AI can help answer questions, translate languages, summarize documents, assist with coding, analyse data, recognize images and speech, detect patterns, recommend content, support accessibility, assist research, generate text and other media, and automate repetitive tasks. Important decisions should include appropriate human review."),

        ((
            "how ai can help",
            "how can ai help",
            "how ai helps",
            "benefits of ai",
        ),
         "AI can save time, assist repetitive work, make information easier to understand, identify patterns in large datasets, personalize learning, improve accessibility, support creativity, and help people explore ideas. It is a support technology rather than a guarantee that every answer or prediction is correct."),

        ((
            "programming language",
            "best language for ai",
            "which language for ai",
            "language used in ai",
        ),
         "Python is a strong first programming language for AI because of its readable syntax and large ecosystem. Other useful languages include R for statistics, SQL for data work, C++ for performance-sensitive systems, Java for some enterprise applications, and JavaScript or TypeScript for web-based AI applications. The best language depends on the project."),

        ((
            "advantages of ai",
            "advantage of ai",
            "pros of ai",
        ),
         "Advantages of AI can include automation, fast processing, pattern detection, personalized assistance, accessibility support, help with research and creativity, and analysis of large datasets. These benefits depend on good design, suitable data and human oversight."),

        ((
            "disadvantages of ai",
            "disadvantage of ai",
            "cons of ai",
            "limitations of ai",
        ),
         "AI limitations include incorrect or invented outputs, bias, privacy and security risks, dependence on data quality, computing costs for some systems, possible job disruption, misuse for scams or misleading media, and limited understanding of real-world context. Important outputs should be verified."),

        ((
            "when started ai",
            "when did ai start",
            "history of ai",
            "origin of ai",
        ),
         "AI research has roots before the 1950s. The term Artificial Intelligence was proposed by John McCarthy for the Dartmouth Summer Research Project in 1956, an event widely regarded as an important founding point for AI as a research field. AI was developed by many researchers over many decades."),

        ((
            "who started ai",
            "who invented ai",
            "founder of ai",
            "who created artificial intelligence",
        ),
         "John McCarthy is widely associated with the founding of AI as a research field and coined the term Artificial Intelligence. The 1956 Dartmouth project also involved important researchers including Marvin Minsky, Nathaniel Rochester and Claude Shannon. AI was not invented by one person alone."),

        ((
            "how ai helps in developing robotics",
            "how ai helps robotics",
            "robotics and ai",
            "ai and robotics",
        ),
         "AI helps robots interpret sensor and camera data, recognize objects, understand speech, plan routes, avoid obstacles, make decisions and adapt to changing environments. Robotics also requires mechanical engineering, electronics, sensors, control systems, embedded software and safety engineering."),

        ((
            "is ai good",
            "is ai bad",
            "ai good or bad",
            "ai safe",
        ),
         "AI is not automatically good or bad. Its effects depend on how it is designed and used. It can provide useful benefits, while poor or harmful use can create errors, bias, privacy problems, scams or other risks. Responsible AI uses testing, security, privacy protection, fairness and human oversight."),

        ((
            "how ai can help for students",
            "how ai helps students",
            "ai for students",
            "students with ai",
            "how ai helps for students",
        ),
         "AI can help students understand difficult concepts, create practice questions, practise languages, summarize notes, organize study plans, receive feedback on drafts and practise coding. Students should do their own learning, verify facts and follow their school or college rules. AI should not be used to cheat."),

        ((
            "how ai can help for employees",
            "how ai helps employees",
            "ai for employees",
        ),
         "AI can help employees draft and summarize documents, analyse spreadsheets, prepare presentations, search knowledge, translate text, brainstorm, automate routine workflows and assist with coding. Employees should protect confidential information and verify important outputs."),

        ((
            "help for creators",
            "ai for creators",
            "content creators",
            "creative work",
        ),
         "Creators can use AI to brainstorm ideas, outline scripts, draft captions, create storyboards, assist with audio and video editing, generate concepts, create subtitles, translate content and organize production. Creators should check accuracy, copyright and licensing requirements and avoid presenting synthetic media as real evidence."),

        ((
            "machine learning",
            "deep learning",
            "neural network",
            "large language model",
            "llm",
        ),
         "Machine learning is an approach within AI where models learn patterns from data. Deep learning uses multi-layer neural networks and is useful for image, speech and language tasks. Large language models are trained to process and generate language. These systems can be powerful but can still produce incorrect outputs."),
    ]

    # Specific rules must win over broad rules.  Score the *actual matched
    # phrase*, rather than the longest phrase stored in a rule.  This prevents
    # a broad phrase such as "about ai" from beating "tell me about ai
    # automobiles" merely because the rule contains another long alias.
    best_answer = None
    best_match_length = -1
    for phrases, answer in answers:
        for phrase in phrases:
            if phrase in cleaned:
                length = len(phrase.split())
                if length > best_match_length:
                    best_match_length = length
                    best_answer = answer
    if best_answer is not None:
        speak(best_answer)
        return True

    speak("I have an offline AI knowledge center covering AI development, chatbots, applications, websites, automobiles, careers, AI-engineer roadmaps, prompt engineering, data science, machine learning, education, creators and everyday uses. Please ask a specific AI question.")
    return True





# ---------------------- Command 12: Offline Spiritual & Religious Knowledge Center ----------------------

def handle_command12(command):
    """
    Offline knowledge center for gods/deities, holy books and scriptures,
    temples and other places of worship, darshan, and spiritual stories.

    This handler intentionally uses only built-in knowledge and does not
    perform live searches or current-information lookups.
    Faith-specific claims are framed as teachings/traditions rather than as
    scientific facts, and places of worship are described respectfully.
    """
    cleaned = normalize_command(command)
    cleaned = strip_assistant_address(cleaned)
    if not cleaned:
        return False

    # Common voice/ASR variants.
    aliases = {
        "lord krishna": "krishna",
        "krishna": "krishna",
        "lord rama": "rama",
        "rama": "rama",
        "lord ram": "rama",
        "ram": "rama",
        "lord shiva": "shiva",
        "shiva": "shiva",
        "mahadev": "shiva",
        "lord vishnu": "vishnu",
        "vishnu": "vishnu",
        "lord ganesha": "ganesha",
        "ganesha": "ganesha",
        "ganapati": "ganesha",
        "vinayaka": "ganesha",
        "goddess lakshmi": "lakshmi",
        "lakshmi": "lakshmi",
        "goddess saraswati": "saraswati",
        "saraswati": "saraswati",
        "goddess durga": "durga",
        "durga": "durga",
        "goddess parvati": "parvati",
        "parvati": "parvati",
        "goddess kamakshi": "kamakshi",
        "kamakshi": "kamakshi",
        "kamakshamma": "kamakshamma",
        "kamakshamma devi": "kamakshamma",
        "chenchu lakshmiamma": "chenchu lakshmi amma",
        "chenchu lakshmi amma": "chenchu lakshmi amma",
        "lord hanuman": "hanuman",
        "hanuman": "hanuman",
        "anjaneya": "hanuman",
        "lord venkateswara": "venkateswara",
        "venkateswara": "venkateswara",
        "venkateshwara": "venkateswara",
        "balaji": "venkateswara",
        "lord brahma": "brahma",
        "brahma": "brahma",
        "lord ayyappa": "ayyappa",
        "lord ayyapa": "ayyappa",
        "ayyappa": "ayyappa",
        "ayyapa": "ayyappa",
        "ayyappan": "ayyappa",
        "lord subramanyam swamy": "subramanyam",
        "subramanyam swamy": "subramanyam",
        "subramanyam": "subramanyam",
        "subramanya": "subramanyam",
        "lord murugan": "murugan",
        "murugan": "murugan",
        "lord murgan": "murugan",
        "murgan": "murugan",
        "lord narasimha swamy": "narasimha",
        "lord narshima swamy": "narasimha",
        "narasimha swamy": "narasimha",
        "narshima swamy": "narasimha",
        "narasimha": "narasimha",
        "narsimha": "narasimha",
        "lord buddha": "buddha",
        "lord budha": "buddha",
        "buddha": "buddha",
        "budha": "buddha",
        "jesus": "jesus",
        "jesus christ": "jesus",
        "christ": "jesus",
        "allah": "allah",
    }

    god_answers = {
        "krishna": (
            "Lord Krishna is a central figure in Hindu traditions and is widely revered as an avatar of Vishnu. "
            "He is associated with the Mahabharata, the Bhagavad Gita, and devotional traditions. Krishna's childhood "
            "stories describe his life in Gokul and Vrindavan, while the Bhagavad Gita presents his teaching to Arjuna "
            "on duty, selfless action, devotion, knowledge, and spiritual discipline. Different Hindu traditions explain "
            "Krishna's divine nature in different ways, including as the Supreme Being or as an incarnation of Vishnu."
        ),
        "rama": (
            "Lord Rama is a major figure in Hindu tradition and is widely regarded as an avatar of Vishnu. "
            "His life is narrated most famously in the Ramayana. Rama is traditionally associated with dharma, "
            "truthfulness, responsibility, courage, compassion, and devotion to duty. The story includes Sita, Lakshmana, "
            "Hanuman, the exile into the forest, the abduction of Sita, and the battle with Ravana."
        ),
        "shiva": (
            "Lord Shiva is one of the principal deities of Hindu traditions and is often associated with transformation, "
            "meditation, asceticism, and the dissolution that makes renewal possible. He is commonly depicted with the "
            "trident, matted hair, crescent moon, and the river Ganga, and is worshipped in forms including the Shiva Linga. "
            "Traditions also describe Shiva as Mahadeva, Nataraja, and the compassionate divine presence who grants grace."
        ),
        "vishnu": (
            "Lord Vishnu is one of the principal deities in Hindu traditions and is widely associated with preservation "
            "and protection of the cosmic order. Hindu traditions describe Vishnu through many forms and avatars, including "
            "Rama, Krishna, and Narasimha. Vishnu is often depicted reclining on the serpent Ananta and accompanied by Goddess Lakshmi."
        ),
        "ganesha": (
            "Lord Ganesha is a widely worshipped Hindu deity associated with wisdom, learning, auspicious beginnings, "
            "and the removal of obstacles. He is traditionally depicted with an elephant head and a human body. "
            "Popular stories describe his devotion to his parents Shiva and Parvati and explain the symbolism of his elephant head."
        ),
        "lakshmi": (
            "Goddess Lakshmi is widely revered in Hindu traditions as a goddess associated with prosperity, abundance, "
            "good fortune, beauty, and auspiciousness. She is traditionally described as the consort of Vishnu and is especially "
            "worshipped during festivals such as Diwali and Lakshmi Puja."
        ),
        "saraswati": (
            "Goddess Saraswati is widely revered in Hindu traditions as a goddess associated with knowledge, learning, "
            "wisdom, speech, music, and the arts. She is commonly depicted with a veena and a book, and is especially "
            "honoured by students, teachers, musicians, and scholars during festivals such as Vasant Panchami."
        ),
        "durga": (
            "Goddess Durga is a major Hindu goddess associated with strength, protection, courage, and the triumph of good "
            "over evil. A well-known tradition tells of Durga defeating the buffalo demon Mahishasura. She is commonly shown "
            "riding a lion or tiger and carrying symbolic weapons given by the gods."
        ),
        "parvati": (
            "Goddess Parvati is a major Hindu goddess and is traditionally described as the consort of Shiva and the mother "
            "of Ganesha and Kartikeya. Hindu traditions present her through many forms, including Durga and other powerful "
            "or benevolent manifestations. She is associated with motherhood, devotion, strength, love, and divine energy."
        ),
        "kamakshi": (
            "Goddess Kamakshi is a revered form of the Divine Mother in Hindu Shakta traditions. She is especially associated "
            "with the Kamakshi Amman Temple at Kanchipuram in Tamil Nadu. The name is commonly interpreted through the ideas "
            "of compassion, divine vision, and the power of the Goddess."
        ),
        "kamakshamma": (
            "Kamakshamma is a revered local form of the Divine Mother in regional South Indian devotional traditions. "
            "Local temple traditions can differ in their history, festivals, legends, and forms of worship. For a specific "
            "Kamakshamma temple, Sara can explain the general spiritual significance without inventing local historical details."
        ),
        "chenchu lakshmi amma": (
            "Chenchu Lakshmi Amma is a revered figure in regional South Indian devotional tradition, especially in traditions "
            "connected with the Chenchu community and the sacred Narasimha tradition. Accounts and local worship practices can "
            "vary by temple and region, so Sara will describe the traditional belief respectfully rather than present one local "
            "version as the only historical account."
        ),
        "hanuman": (
            "Lord Hanuman is a central figure in the Ramayana and is widely revered in Hindu traditions as a symbol of devotion, "
            "strength, courage, humility, and service. He is traditionally devoted to Lord Rama and plays a major role in the search "
            "for Sita and the battle against Ravana. Hanuman is also associated with the ability to overcome fear and obstacles."
        ),
        "venkateswara": (
            "Lord Venkateswara, also called Venkatachalapati or Balaji in devotional usage, is a highly revered form of Vishnu. "
            "He is especially associated with Tirumala in Andhra Pradesh, where the Sri Venkateswara Swamy Temple is one of the "
            "world's most visited pilgrimage centres. Devotional traditions connect Venkateswara with protection, compassion, "
            "and the fulfilment of devotees' prayers."
        ),
        "brahma": (
            "Lord Brahma is a principal deity in Hindu traditions associated with creation. He is traditionally depicted with four "
            "faces and four arms and is associated with Saraswati in many traditions. In Hindu philosophy, creation, preservation, "
            "and dissolution are often discussed through Brahma, Vishnu, and Shiva respectively, although the exact theological "
            "interpretation differs among traditions."
        ),
        "ayyappa": (
            "Lord Ayyappa is a widely worshipped Hindu deity, especially associated with the Sabarimala pilgrimage in Kerala. "
            "Devotional traditions identify him with Harihara, expressing a connection of Vishnu and Shiva, and describe him as "
            "a disciplined and protective deity. Sabarimala worship includes a period of vrata or disciplined observance before pilgrimage."
        ),
        "subramanyam": (
            "Lord Subramanya, also known as Kartikeya, Skanda, or Murugan, is a major Hindu deity associated with courage, "
            "wisdom, victory, and divine protection. He is traditionally described as a son of Shiva and Parvati and is especially "
            "revered in South India. His vahana is commonly described as the peacock, and his spear is called the Vel."
        ),
        "murugan": (
            "Lord Murugan is a major Tamil and South Indian form of Kartikeya or Skanda. He is widely worshipped as a youthful "
            "warrior deity associated with courage, wisdom, victory, and spiritual discipline. Important pilgrimage traditions "
            "include the six sacred abodes of Murugan in Tamil Nadu."
        ),
        "narasimha": (
            "Lord Narasimha is a famous avatar of Vishnu in Hindu traditions, depicted as part human and part lion. "
            "The Narasimha story centres on protecting Prahlada and defeating the powerful demon king Hiranyakashipu. "
            "The story is traditionally understood as illustrating divine protection, devotion, and the defeat of arrogance and tyranny."
        ),
        "buddha": (
            "The Buddha, meaning an awakened or enlightened one, refers especially to Siddhartha Gautama, whose teachings became "
            "the foundation of Buddhism. Buddhism generally does not describe the Buddha simply as a creator god. His teachings focus "
            "on suffering, its causes, the possibility of its cessation, and the path of practice leading toward liberation, including "
            "the Noble Eightfold Path."
        ),
        "jesus": (
            "Jesus Christ is the central figure of Christianity. Christians believe that Jesus is the Son of God and the Messiah, "
            "and Christian teachings centre on his life, teachings, crucifixion, and resurrection. The New Testament Gospels narrate "
            "many events from his life, including his teachings about love, forgiveness, compassion, faith, and the Kingdom of God."
        ),
        "allah": (
            "Allah is the Arabic word for God and is the name used by Muslims for the one God. In Islam, Allah is understood as the "
            "one, unique, merciful, and all-powerful Creator. Islamic teachings about Allah are expressed throughout the Quran, with "
            "strong emphasis on monotheism, worship, mercy, justice, and accountability."
        ),
    }

    book_answers = {
        "bhagavad gita": (
            "The Bhagavad Gita is a Sanskrit Hindu scripture presented as a dialogue between Krishna and Arjuna in the "
            "Mahabharata. It discusses dharma, action, devotion, knowledge, meditation, the nature of the self, and liberation. "
            "Its teachings are interpreted in different ways by Hindu philosophical traditions."
        ),
        "ramayana": (
            "The Ramayana is an ancient Indian epic traditionally attributed to the sage Valmiki. It tells the story of Rama, "
            "Sita, Lakshmana, Hanuman, and their struggle against Ravana. It explores themes such as dharma, loyalty, courage, "
            "devotion, duty, and the consequences of moral choices. There are many regional and religious retellings of the story."
        ),
        "mahabharata": (
            "The Mahabharata is one of the major Sanskrit epics of India. It centres on the conflict between the Pandavas and "
            "Kauravas and contains teachings, stories, philosophical discussions, and the Bhagavad Gita. Traditionally attributed "
            "to Vyasa, it explores dharma, duty, family conflict, justice, war, and the consequences of human choices."
        ),
        "vedas": (
            "The Vedas are the oldest major layer of Sanskrit sacred literature in the Vedic tradition. The four commonly recognised "
            "Vedas are the Rigveda, Samaveda, Yajurveda, and Atharvaveda. They contain hymns, ritual material, prayers, and related "
            "knowledge transmitted through long oral traditions."
        ),
        "upanishads": (
            "The Upanishads are philosophical and spiritual texts associated with the later portions of Vedic literature. "
            "They explore ideas such as Brahman, Atman, consciousness, knowledge, meditation, and liberation. Different Upanishads "
            "and philosophical schools interpret these concepts in different ways."
        ),
        "puranas": (
            "The Puranas are a large body of Hindu religious literature containing narratives about deities, creation, cosmology, "
            "genealogies, sacred places, festivals, moral teachings, and devotional practices. Important examples include the "
            "Bhagavata Purana, Vishnu Purana, Shiva Purana, and Devi Bhagavata Purana."
        ),
        "bible": (
            "The Bible is the collection of sacred scriptures of Christianity. It is divided into the Old Testament and New Testament "
            "in most Christian traditions, although the exact collection of books differs among denominations. It contains history, "
            "poetry, wisdom literature, prophecy, teachings, letters, and the Gospel accounts of Jesus."
        ),
        "quran": (
            "The Quran is the central sacred scripture of Islam. Muslims believe it is the word of Allah revealed to the Prophet "
            "Muhammad through the angel Jibril. It teaches monotheism, worship, moral conduct, justice, mercy, accountability, and "
            "guidance for life."
        ),
        "guru granth sahib": (
            "The Guru Granth Sahib is the central scripture and eternal Guru of Sikhism. It contains hymns and teachings of Sikh Gurus "
            "and other revered saints. Its teachings emphasise devotion to one God, equality, truthful living, remembrance of the divine, "
            "service, humility, and rejection of caste-based discrimination."
        ),
        "buddhist scriptures": (
            "Buddhist scriptures are a broad collection rather than a single universal book. Major traditions preserve different canons, "
            "including the Pali Canon or Tipitaka in Theravada Buddhism and extensive sutra and commentary traditions in Mahayana and "
            "Vajrayana Buddhism. They contain teachings on ethics, meditation, wisdom, compassion, and liberation."
        ),
        "jain scriptures": (
            "Jain scriptures are preserved in different textual traditions, especially among the Svetambara and Digambara communities. "
            "Jain teachings emphasise ahimsa or non-violence, truth, non-attachment, self-discipline, and liberation. Important texts "
            "include the Agamas in the Svetambara tradition and major philosophical works preserved in Jain literary traditions."
        ),
    }

    place_answers = {
        "tirumala tirupati temple": (
            "The Sri Venkateswara Swamy Temple at Tirumala, near Tirupati in Andhra Pradesh, is one of the most important Hindu "
            "pilgrimage centres. It is dedicated to Lord Venkateswara, a form of Vishnu. Devotees visit for darshan, worship, vows, "
            "and offerings. The Tirumala hills and their pilgrimage traditions are deeply connected with the worship of Venkateswara."
        ),
        "tirumala": (
            "Tirumala is the sacred hill area associated with the Sri Venkateswara Swamy Temple and the pilgrimage to Lord Venkateswara. "
            "It is part of the Tirumala Hills near Tirupati in Andhra Pradesh and is one of the best-known Hindu pilgrimage destinations."
        ),
        "arunachalam": (
            "Arunachalam, centred on the sacred Arunachala Hill at Tiruvannamalai in Tamil Nadu, is a major Shaiva pilgrimage site. "
            "The Arunachalesvara Temple is dedicated to Shiva, and the hill is revered as a sacred manifestation associated with Shiva. "
            "The Girivalam or circumambulation of Arunachala is an important devotional practice."
        ),
        "srisailam": (
            "Srisailam in Andhra Pradesh is a major Shaiva and Shakta pilgrimage centre. The Mallikarjuna Swamy Temple is dedicated to "
            "Lord Shiva as Mallikarjuna, and the Bhramaramba shrine honours the Goddess. Srisailam is also associated with the Nallamala "
            "hills and the Krishna River."
        ),
        "srikalahasti": (
            "Srikalahasti in Andhra Pradesh is a famous Shaiva temple town. Sri Kalahasteeswara Temple is dedicated to Shiva and is "
            "traditionally associated with the Vayu element among the Pancha Bhoota or five-element temples of Shiva. The temple is also "
            "well known for devotional and Rahu-Ketu related worship traditions."
        ),
        "kanipakam": (
            "Kanipakam in Andhra Pradesh is famous for the Sri Varasiddhi Vinayaka Swamy Temple, dedicated to Lord Ganesha. "
            "The temple has a long devotional tradition and is especially associated with worship of Vinayaka and the belief that the "
            "self-manifested deity has a sacred presence."
        ),
        "kashi vishwanath": (
            "The Kashi Vishwanath Temple in Varanasi, Uttar Pradesh, is one of the most revered Shiva temples. It is associated with "
            "the Jyotirlinga tradition and stands in the sacred city of Kashi. Pilgrimage to Kashi and worship of Vishwanath have a very "
            "long history in Hindu tradition."
        ),
        "kedarnath": (
            "Kedarnath in Uttarakhand is a major Himalayan pilgrimage site dedicated to Lord Shiva. Kedarnath Temple is traditionally "
            "included among the twelve Jyotirlingas and is one of the important Char Dham pilgrimage sites in the Himalayan region."
        ),
        "badrinath": (
            "Badrinath in Uttarakhand is a major Vaishnava pilgrimage centre dedicated to Lord Vishnu in the form of Badrinath. "
            "It is one of the Char Dham pilgrimage sites and is situated in the Himalayan region along the Alaknanda River."
        ),
        "rameswaram": (
            "Rameswaram in Tamil Nadu is a major Hindu pilgrimage centre. Ramanathaswamy Temple is dedicated to Lord Shiva and is "
            "traditionally associated with the Ramayana and Lord Rama. It is one of the twelve Jyotirlinga sites in Hindu tradition and "
            "is also part of the Char Dham tradition."
        ),
        "ayodhya": (
            "Ayodhya in Uttar Pradesh is a major Hindu pilgrimage city traditionally associated with Lord Rama and the Ramayana. "
            "It contains important sacred sites connected with Rama traditions and is also historically significant in Indian religious culture."
        ),
        "jagannath puri": (
            "Jagannath Puri in Odisha is one of India's major Hindu pilgrimage centres. The Jagannath Temple is dedicated to Lord Jagannath, "
            "a form of Vishnu or Krishna in Vaishnava traditions. The annual Rath Yatra is one of the best-known festivals associated with the temple."
        ),
        "meena kshi temple": "",
        "meenakshi temple": (
            "The Meenakshi Amman Temple in Madurai, Tamil Nadu, is a major historic Hindu temple dedicated to Goddess Meenakshi, "
            "a form of Parvati, and Lord Sundareshwarar, a form of Shiva. The temple is famous for its large gopurams, sculptural detail, "
            "ritual traditions, and its central role in Madurai's religious and cultural life."
        ),
        "golden temple": (
            "The Golden Temple, formally Harmandir Sahib, in Amritsar, Punjab, is the central place of worship of Sikhism. "
            "It is known for its golden-covered sanctum, the sacred pool, the Guru Granth Sahib, and the tradition of langar, a community "
            "kitchen serving people regardless of background. It is more accurately called a gurdwara rather than a Hindu temple."
        ),
        "kamakshamma temple": (
            "Kamakshamma temples are local shrines dedicated to a form of the Goddess in regional South Indian traditions. "
            "The exact history, location, deity form, festivals, and legends vary from one temple to another, so Sara will not invent "
            "specific local details without a location."
        ),
        "koti lingalu": (
            "Koti Lingala is a sacred place associated with Shiva worship in Andhra Pradesh and Telangana traditions. The phrase "
            "Koti Lingalu refers to the devotional idea of many or countless Shiva Lingas. Different places may be described by similar names, "
            "so the exact local site should be specified when a detailed history is needed."
        ),
        "varanasi": (
            "Varanasi, also called Kashi or Banaras, is one of the oldest continuously inhabited cities and one of the most sacred pilgrimage "
            "cities in Hindu traditions. It is situated on the Ganga and is associated with temples, ghats, Shiva worship, pilgrimage, and "
            "the Ganga Aarti. It is also an important cultural and spiritual centre."
        ),
        "isha foundation coimbatore": (
            "Isha Yoga Center near Coimbatore in Tamil Nadu is a spiritual and yoga centre founded by Sadhguru. It is known for yoga programs, "
            "meditation-related activities, the Dhyanalinga, and the Adiyogi statue. It is better described as a spiritual and yoga centre "
            "rather than as a traditional Hindu temple."
        ),
    }

    story_answers = {
        "krishna childhood stories": (
            "Traditional Krishna childhood stories describe his birth in Mathura, his journey to Gokul, and his childhood in the pastoral "
            "community of Gokul and Vrindavan. Famous episodes include his playful stealing of butter, his friendship with the cowherd boys, "
            "his lifting of Govardhan Hill according to devotional tradition, and his encounters with Kaliya. These stories are especially "
            "prominent in Bhagavata Purana and later devotional literature."
        ),
        "rama life stories": (
            "The traditional Ramayana story follows Rama from his youth and marriage to Sita through his exile, the abduction of Sita by Ravana, "
            "the alliance with Sugriva and Hanuman, the search for Sita, the journey to Lanka, the battle with Ravana, and Rama's return. "
            "The story is commonly interpreted through themes of dharma, loyalty, courage, sacrifice, and devotion."
        ),
        "hanuman stories": (
            "Important Hanuman stories include his childhood encounter with the Sun, his meeting with Rama, his leap across the ocean in search "
            "of Sita, his meeting with Sita in Lanka, the burning of Lanka in the traditional narrative, and carrying the mountain containing "
            "the Sanjeevani herb to help Lakshmana. These stories emphasise devotion, courage, strength, humility, and service."
        ),
        "ganesha stories": (
            "A famous Ganesha story tells how Parvati created Ganesha to guard her privacy. When Shiva returned, a conflict occurred and Ganesha "
            "was beheaded in the traditional narrative. Shiva then restored him with an elephant head. Another famous story describes Ganesha "
            "and Kartikeya competing to circle the world, with Ganesha explaining that his parents represented the world to him."
        ),
        "shiva stories": (
            "Traditional Shiva stories include the descent of the Ganga through Shiva's matted hair, the churning of the cosmic ocean and Shiva "
            "holding the poison in his throat, the destruction of Tripura, the marriage of Shiva and Parvati, and the appearance of Shiva as "
            "Nataraja. Different Puranic and regional traditions tell these stories with variations."
        ),
        "mahabharata stories": (
            "Famous Mahabharata stories include the childhood of the Pandavas and Kauravas, the Pandavas' exile, Draupadi's swayamvara, the dice game, "
            "the forest years, Krishna's role as guide and diplomat, the Bhagavad Gita on the battlefield of Kurukshetra, and the final war. "
            "The epic explores dharma, duty, loyalty, justice, ambition, and the consequences of choices."
        ),
        "ramayana stories": (
            "The Ramayana contains many stories: Rama's birth and youth, his marriage to Sita, the exile to the forest, the golden deer episode, "
            "Sita's abduction by Ravana, Hanuman's journey to Lanka, the building of the bridge to Lanka in the traditional narrative, the battle "
            "with Ravana, and Rama's return to Ayodhya. Regional retellings can differ in details."
        ),
        "stories from the puranas": (
            "The Puranas contain many spiritual stories, including stories of Vishnu's avatars, Shiva and Parvati, Devi and the Goddess, Prahlada and "
            "Narasimha, Dhruva's devotion, the churning of the ocean, creation traditions, sacred places, and the lives of devotees. Different Puranas "
            "emphasise different deities and theological traditions."
        ),
        "moral spiritual stories": (
            "A simple spiritual lesson is the story of Prahlada in Hindu tradition. Prahlada remains devoted to Vishnu even when his father, "
            "Hiranyakashipu, opposes his devotion. The story traditionally teaches steadfast faith, courage, humility, and the idea that devotion "
            "can remain strong even during hardship."
        ),
        "jesus story": (
            "The Christian story of Jesus is told primarily in the four Gospels of the New Testament. They describe his birth and early life in "
            "different ways, his baptism, teachings and ministry, healings and parables, his entry into Jerusalem, crucifixion, and resurrection. "
            "For Christians, the resurrection is central to the faith and to the belief that Jesus is the Messiah and Son of God."
        ),
    }

    # Priority answers for reported Command 12 bug cases.
    # These exact natural-language forms are checked before the broader
    # category routing below, so each requested question gets a dedicated,
    # complete offline answer.
    priority_answers = {
        "what does bhagavad gita teach": (
            "According to the Bhagavad Gita, Krishna teaches Arjuna about dharma, or responsible duty, and how to perform one's duties without being controlled by attachment to the results. The Gita discusses selfless action, devotion to God, knowledge, meditation, discipline, the nature of the self, and liberation. It teaches that a person should act responsibly, develop self-control, seek spiritual understanding, and dedicate action to a higher purpose. Different Hindu philosophical traditions interpret the Gita's teachings in different ways."
        ),
        "what are the vedas": (
            "The Vedas are a foundational body of sacred Sanskrit literature in the Vedic tradition. The four commonly recognised Vedas are the Rigveda, Samaveda, Yajurveda, and Atharvaveda. They contain hymns, prayers, ritual instructions, chants, and related sacred knowledge that was preserved through long oral traditions. The Vedas are among the oldest layers of Sanskrit religious literature and form an important foundation for later Hindu traditions."
        ),
        "what are upanishads": (
            "The Upanishads are philosophical and spiritual texts associated with the later portions of Vedic literature. They explore deep questions about the self, ultimate reality, consciousness, knowledge, meditation, karma, and liberation. Concepts such as Atman, the self, and Brahman, ultimate reality, are central in many Upanishads. Different Hindu philosophical schools interpret these teachings in different ways."
        ),
        "what are the upanishads": (
            "The Upanishads are philosophical and spiritual texts associated with the later portions of Vedic literature. They explore deep questions about the self, ultimate reality, consciousness, knowledge, meditation, karma, and liberation. Concepts such as Atman, the self, and Brahman, ultimate reality, are central in many Upanishads. Different Hindu philosophical schools interpret these teachings in different ways."
        ),
        "what are the puranas": (
            "The Puranas are a large body of Hindu religious literature containing stories and teachings about deities, creation, cosmology, genealogies, sacred places, festivals, moral values, and devotional practices. Major examples include the Bhagavata Purana, Vishnu Purana, Shiva Purana, and Devi Bhagavata Purana. Different Puranas emphasise different deities and theological traditions, and their stories are an important part of Hindu devotional culture."
        ),
        "what are puranas": (
            "The Puranas are a large body of Hindu religious literature containing stories and teachings about deities, creation, cosmology, genealogies, sacred places, festivals, moral values, and devotional practices. Major examples include the Bhagavata Purana, Vishnu Purana, Shiva Purana, and Devi Bhagavata Purana. Different Puranas emphasise different deities and theological traditions, and their stories are an important part of Hindu devotional culture."
        ),
        "tell me about lord venkateswara temple": (
            "The Sri Venkateswara Swamy Temple at Tirumala, near Tirupati in Andhra Pradesh, is a major Hindu pilgrimage centre dedicated to Lord Venkateswara, a revered form of Vishnu. Devotees visit the temple for darshan, worship, vows, and offerings. Tirumala is known for its sacred hill setting and long devotional traditions. The temple is especially important in Vaishnava worship, and millions of pilgrims visit it over time."
        ),
        "tell me about koti lingalu temple": (
            "Koti Lingalu refers to a sacred place associated with Shiva worship and the devotional tradition of many Shiva Lingas. The name is used for sacred sites connected with the idea of numerous or countless Lingas, and local traditions can differ. Because more than one place can be described with similar names, Sara should not invent a specific temple history without identifying the exact location."
        ),
        "tell me about koti lingalu": (
            "Koti Lingalu refers to a sacred place associated with Shiva worship and the devotional tradition of many Shiva Lingas. The name is used for sacred sites connected with the idea of numerous or countless Lingas, and local traditions can differ. Because more than one place can be described with similar names, Sara should not invent a specific temple history without identifying the exact location."
        ),
        "tell me about isha temple in coimbatore": (
            "The Isha Yoga Center near Coimbatore, Tamil Nadu, is a spiritual and yoga centre founded by Sadhguru. It is known for yoga and meditation-related programs, the Dhyanalinga, and the large Adiyogi statue. It is more accurately described as a spiritual and yoga centre rather than a traditional Hindu temple. Visitors may participate in spiritual, yoga, meditation, and cultural activities according to the centre's traditions and programs."
        ),
        "tell me about hindu temples": (
            "Hindu temples are sacred places where devotees worship deities, perform rituals, offer prayers, receive darshan, and participate in festivals and community traditions. A temple may contain a main shrine with a murti or sacred representation of a deity, along with other shrines and ritual spaces. Common practices can include puja, archana, abhishekam, pradakshina, offerings, chanting, and receiving prasadam. Temple traditions vary greatly by region, deity, sect, and local custom."
        ),
        "tell me a story about rama": (
            "A well-known story from the Ramayana describes Rama's exile into the forest. Rama, Sita, and Lakshmana leave Ayodhya and live in the forest. Later, Ravana abducts Sita, and Rama begins the search for her. Rama forms an alliance with Sugriva and meets Hanuman, whose devotion and courage become central to the search. Hanuman reaches Lanka and finds Sita. Rama's forces then travel to Lanka, and in the traditional narrative Rama defeats Ravana and rescues Sita. The story is traditionally associated with dharma, courage, loyalty, sacrifice, and devotion."
        ),
        "can you tell me the story of hanuman": (
            "One famous Hanuman story comes from the Ramayana tradition. Hanuman becomes a devoted follower of Rama and helps him search for Sita after her abduction by Ravana. Hanuman crosses the ocean to Lanka, finds Sita, gives her Rama's message, and returns with information about her location. In later events he helps Rama's forces during the battle. Another famous episode tells how Hanuman carries a mountain containing the Sanjeevani herb when Lakshmana is seriously injured. These stories traditionally emphasise devotion, courage, strength, humility, service, and faith."
        ),
        "tell me something spiritual": (
            "A simple spiritual lesson is the importance of compassion, self-control, honesty, and service. Many religious traditions teach that spiritual life is not only about rituals but also about how a person treats others and responds to difficulties. In Hindu traditions, for example, the Bhagavad Gita discusses disciplined action, devotion, knowledge, and freedom from excessive attachment to results. Different faiths express spiritual teachings in their own ways, so Sara will keep their traditions distinct and describe them respectfully."
        ),
        "tell me about hindu holy books": (
            "Hindu sacred literature is a large and diverse tradition rather than a single holy book. Important texts include the Vedas, Upanishads, Bhagavad Gita, Ramayana, Mahabharata, and Puranas. The Vedas are foundational Vedic scriptures; the Upanishads explore philosophical and spiritual questions; the Bhagavad Gita presents Krishna's dialogue with Arjuna; the Ramayana and Mahabharata are major epics; and the Puranas contain many devotional stories and teachings. Different Hindu traditions give different texts particular importance."
        ),
        "whats the hindus holy book": (
            "Hinduism does not have one single holy book shared by all Hindus in the same way that some religions have a central scripture. Hindu sacred literature includes the Vedas, Upanishads, Bhagavad Gita, Ramayana, Mahabharata, Puranas, and many other texts. The Bhagavad Gita is one of the most widely studied Hindu scriptures, while the Vedas are among the oldest foundational sacred texts."
        ),
        "what is the hindus holy book": (
            "Hinduism does not have one single holy book shared by all Hindus in the same way that some religions have a central scripture. Hindu sacred literature includes the Vedas, Upanishads, Bhagavad Gita, Ramayana, Mahabharata, Puranas, and many other texts. The Bhagavad Gita is one of the most widely studied Hindu scriptures, while the Vedas are among the oldest foundational sacred texts."
        ),
        "whats the christian holy book": (
            "The Bible is the central collection of sacred scriptures of Christianity. It contains the Old Testament and New Testament in most Christian traditions, although the exact collection of books differs among Christian denominations. The New Testament includes the four Gospels, which describe the life and teachings of Jesus, as well as his crucifixion and resurrection."
        ),
        "what is the christian holy book": (
            "The Bible is the central collection of sacred scriptures of Christianity. It contains the Old Testament and New Testament in most Christian traditions, although the exact collection of books differs among Christian denominations. The New Testament includes the four Gospels, which describe the life and teachings of Jesus, as well as his crucifixion and resurrection."
        ),
        "whats the muslim holy book": (
            "The Quran is the central sacred scripture of Islam. Muslims believe that the Quran is the word of Allah revealed to the Prophet Muhammad through the angel Jibril. It teaches monotheism, worship, moral conduct, justice, mercy, accountability, and guidance for life."
        ),
        "what is the muslim holy book": (
            "The Quran is the central sacred scripture of Islam. Muslims believe that the Quran is the word of Allah revealed to the Prophet Muhammad through the angel Jibril. It teaches monotheism, worship, moral conduct, justice, mercy, accountability, and guidance for life."
        ),
        "what are hindu holy books": (
            "Hinduism has a broad and diverse body of sacred literature rather than one single holy book. Major texts include the Vedas, Upanishads, Bhagavad Gita, Ramayana, Mahabharata, and Puranas. Different Hindu traditions and schools place different emphasis on these texts."
        ),
        "what are famous temples": (
            "Famous Hindu pilgrimage temples and sacred places include Tirumala Tirupati, Srisailam, Srikalahasti, Kanipakam, Kashi Vishwanath, Kedarnath, Badrinath, Rameswaram, Jagannath Puri, Meenakshi Temple, Arunachalam, and many others. India also has important places of worship belonging to other religions, such as the Golden Temple in Sikhism, churches in Christianity, and mosques in Islam. Each place has its own religious traditions and history."
        ),
        "tell me about famous temples": (
            "Famous Hindu pilgrimage temples and sacred places include Tirumala Tirupati, Srisailam, Srikalahasti, Kanipakam, Kashi Vishwanath, Kedarnath, Badrinath, Rameswaram, Jagannath Puri, Meenakshi Temple, Arunachalam, and many others. India also has important places of worship belonging to other religions, such as the Golden Temple in Sikhism, churches in Christianity, and mosques in Islam. Each place has its own religious traditions and history."
        ),
        "tell me about religious stories": (
            "Religious stories are traditional narratives that communicate beliefs, values, history, devotion, or moral lessons within a faith tradition. Examples include Krishna stories from Hindu traditions, Rama and Hanuman stories from the Ramayana, stories of Shiva and the Goddess from Hindu traditions, stories from the Puranas, and stories about Jesus from the Christian Gospels. Different religions and communities preserve their stories in different scriptures and traditions, so Sara will identify the tradition rather than mix them together."
        ),
        "what is the importance of bhagavad gita": (
            "The Bhagavad Gita is important in Hindu philosophy and devotional traditions because it presents a dialogue between Krishna and Arjuna about duty, action, devotion, knowledge, self-discipline, and liberation. It has been interpreted by many Hindu teachers and philosophical schools and has influenced spiritual thought, ethics, literature, and religious practice. Its central message is understood differently across traditions, but responsible action, spiritual understanding, and devotion are recurring themes."
        ),
        "what is the difference between ramayana and mahabharata": (
            "The Ramayana and Mahabharata are two major Sanskrit epics of India. The Ramayana primarily tells the story of Rama, Sita, Lakshmana, Hanuman, and Ravana and strongly explores dharma, duty, loyalty, and ideal conduct. The Mahabharata centres on the conflict between the Pandavas and Kauravas and contains a much broader collection of stories, teachings, and philosophical discussions, including the Bhagavad Gita. Both epics explore dharma, family relationships, moral choices, duty, conflict, and the consequences of actions."
        ),
        "what is a holy book": (
            "A holy book, or sacred scripture, is a text that a religious community regards as spiritually authoritative or sacred. It may contain teachings, prayers, laws, stories, history, poetry, wisdom, rituals, or guidance for religious life. Examples include the Bhagavad Gita and Vedas in Hindu traditions, the Bible in Christianity, the Quran in Islam, and the Guru Granth Sahib in Sikhism. Different religions have different ideas about how their scriptures were revealed, transmitted, interpreted, and used."
        ),
        "what is a temple": (
            "A temple is a sacred place used for worship and religious practices. In Hindu traditions, temples commonly contain shrines dedicated to one or more deities and may include rituals such as puja, offerings, chanting, festivals, darshan, and prasadam. Temples can also serve as cultural and community centres. Their architecture, rituals, and traditions vary according to region, deity, sect, and local custom."
        ),
        "what is a pilgrimage": (
            "A pilgrimage is a religious journey to a sacred place undertaken for worship, devotion, prayer, spiritual practice, thanksgiving, or seeking blessings. Examples include journeys to Tirumala, Varanasi, Srisailam, Kedarnath, and many other sacred places in India, as well as pilgrimages in other religions around the world. The practices and meaning of pilgrimage differ between religious traditions."
        ),
        "what is a spiritual story": (
            "A spiritual story is a traditional or reflective story that communicates ideas about faith, devotion, compassion, courage, self-control, morality, purpose, or the relationship between people and the sacred. Such stories occur in many religions. For example, Hindu traditions contain stories of Prahlada, Krishna, Rama, and Hanuman, while Christianity contains stories and parables connected with Jesus."
        ),
        "what is a spiritual story p": (
            "A spiritual story is a traditional or reflective story that communicates ideas about faith, devotion, compassion, courage, self-control, morality, purpose, or the relationship between people and the sacred. Such stories occur in many religions."
        ),
    }

    # Additional natural variants for voice recognition.
    priority_answers.update({
        "tell me about the lord venkateswara temple": priority_answers["tell me about lord venkateswara temple"],
        "tell me about the koti lingalu temple": priority_answers["tell me about koti lingalu temple"],
        "tell me about isha temple coimbatore": priority_answers["tell me about isha temple in coimbatore"],
        "tell me about hindu temple": priority_answers["tell me about hindu temples"],
        "tell me a story of rama": priority_answers["tell me a story about rama"],
        "can you tell me a story about hanuman": priority_answers["can you tell me the story of hanuman"],
        "tell me something spiritual": priority_answers["tell me something spiritual"],
        "tell me about hindu holy book": priority_answers["tell me about hindu holy books"],
        "tell me about the hindu holy books": priority_answers["tell me about hindu holy books"],
        "what is the difference between the ramayana and mahabharata": priority_answers["what is the difference between ramayana and mahabharata"],
        "whats the hindus holy books": priority_answers["whats the hindus holy book"],
        "what's the hindus holy book": priority_answers["whats the hindus holy book"],
        "what's the hindus holy books": priority_answers["whats the hindus holy book"],
        "whats the christians holy book": priority_answers["whats the christian holy book"],
        "what's the christian holy book": priority_answers["whats the christian holy book"],
        "what's the christians holy book": priority_answers["whats the christian holy book"],
        "whats the muslims holy book": priority_answers["whats the muslim holy book"],
        "what's the muslim holy book": priority_answers["whats the muslim holy book"],
        "what's the muslims holy book": priority_answers["whats the muslim holy book"],
    })

    # Exact priority match. This remains fully offline.
    if cleaned in priority_answers:
        speak(priority_answers[cleaned])
        return True

    # Direct general-category questions.
    if cleaned in {"about gods", "about god", "tell me about gods", "tell me about god", "gods", "deities"}:
        speak(
            "SARA's offline spiritual knowledge center can explain major deities and religious figures from Hindu, Christian, Islamic, Buddhist, "
            "Sikh, and Jain traditions, including Krishna, Rama, Shiva, Vishnu, Ganesha, Lakshmi, Saraswati, Durga, Parvati, Kamakshi, "
            "Hanuman, Venkateswara, Ayyappa, Subramanya, Murugan, Narasimha, Buddha, Jesus, and Allah. I will describe each according to "
            "the relevant religious tradition and distinguish belief and tradition from historical or scientific claims."
        )
        return True

    if cleaned in {"about holy books", "holy books", "about scriptures", "holy books and scriptures", "holy books scriptures"}:
        speak(
            "SARA can explain the Bhagavad Gita, Ramayana, Mahabharata, Vedas, Upanishads, Puranas, Bible, Quran, Guru Granth Sahib, "
            "Buddhist scriptures, and Jain scriptures. I will identify the tradition and explain the main themes without mixing different faiths together."
        )
        return True

    if cleaned in {"about temples", "about temple", "temples", "places of worship", "about places of worship"}:
        speak(
            "SARA can explain major pilgrimage places and places of worship including Tirumala Tirupati, Arunachalam, Srisailam, Srikalahasti, "
            "Kanipakam, Kashi Vishwanath, Kedarnath, Badrinath, Rameswaram, Ayodhya, Jagannath Puri, Meenakshi Temple, the Golden Temple, "
            "Kamakshamma temples, Koti Lingalu, Varanasi, Isha Yoga Center near Coimbatore, and general traditions of temples, masjids, "
            "gurdwaras, churches, darshan, and pilgrimage."
        )
        return True

    # Exact story-category questions.
    for phrase, answer in story_answers.items():
        if cleaned == phrase or cleaned == "tell me about " + phrase or cleaned == "tell me " + phrase:
            speak(answer)
            return True

    # Identify a story topic with common natural phrasing.
    story_topic_aliases = {
        "krishna childhood": "krishna childhood stories",
        "krishna childhood story": "krishna childhood stories",
        "childhood stories of krishna": "krishna childhood stories",
        "rama life": "rama life stories",
        "rama story": "rama life stories",
        "life story of rama": "rama life stories",
        "hanuman story": "hanuman stories",
        "stories about hanuman": "hanuman stories",
        "ganesha story": "ganesha stories",
        "stories about ganesha": "ganesha stories",
        "shiva story": "shiva stories",
        "stories about shiva": "shiva stories",
        "mahabharata story": "mahabharata stories",
        "stories about mahabharata": "mahabharata stories",
        "ramayana story": "ramayana stories",
        "stories about ramayana": "ramayana stories",
        "puranic stories": "stories from the puranas",
        "spiritual story": "moral spiritual stories",
        "moral story": "moral spiritual stories",
        "jesus story": "jesus story",
        "story of jesus": "jesus story",
    }
    for alias, target in sorted(story_topic_aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in cleaned and any(word in cleaned for word in ("story", "stories", "tell", "about", "happened")):
            speak(story_answers[target])
            return True

    # Books and scriptures: longest match wins.
    book_aliases = {
        "bhagavad gita": "bhagavad gita",
        "gita": "bhagavad gita",
        "ramayana": "ramayana",
        "mahabharata": "mahabharata",
        "vedas": "vedas",
        "veda": "vedas",
        "upanishads": "upanishads",
        "upanishad": "upanishads",
        "puranas": "puranas",
        "purana": "puranas",
        "bible": "bible",
        "quran": "quran",
        "koran": "quran",
        "guru granth sahib": "guru granth sahib",
        "buddhist scriptures": "buddhist scriptures",
        "buddhist scripture": "buddhist scriptures",
        "jain scriptures": "jain scriptures",
        "jain scripture": "jain scriptures",
    }
    book_candidates = [(alias, target) for alias, target in book_aliases.items() if alias in cleaned]
    if book_candidates and any(x in cleaned for x in ("book", "scripture", "holy", "teach", "about", "what is", "tell me", "explain", "story")):
        alias, target = max(book_candidates, key=lambda item: len(item[0]))
        speak(book_answers[target])
        return True

    # Temples, cities, spiritual centres, and places of worship.
    place_aliases = {
        "tirumala tirupati temple": "tirumala tirupati temple",
        "tirumala tirupati": "tirumala tirupati temple",
        "tirumala temple": "tirumala tirupati temple",
        "tirumala": "tirumala",
        "arunachalam": "arunachalam",
        "arunachala": "arunachalam",
        "srisailam": "srisailam",
        "sri sailam": "srisailam",
        "srikalahasti": "srikalahasti",
        "sri kalahasti": "srikalahasti",
        "kanipakam": "kanipakam",
        "kashi vishwanath": "kashi vishwanath",
        "kedarnath": "kedarnath",
        "badrinath": "badrinath",
        "rameswaram": "rameswaram",
        "rameshwaram": "rameswaram",
        "ayodhya": "ayodhya",
        "jagannath puri": "jagannath puri",
        "puri": "jagannath puri",
        "meenakshi temple": "meenakshi temple",
        "meenakshi amman temple": "meenakshi temple",
        "golden temple": "golden temple",
        "harmandir sahib": "golden temple",
        "kamakshamma temple": "kamakshamma temple",
        "koti lingalu": "koti lingalu",
        "koti lingas": "koti lingalu",
        "varanasi": "varanasi",
        "kashi": "varanasi",
        "isha foundation coimbatore": "isha foundation coimbatore",
        "isha yoga center": "isha foundation coimbatore",
        "isha center": "isha foundation coimbatore",
    }
    place_candidates = [(alias, target) for alias, target in place_aliases.items() if alias in cleaned]
    if place_candidates:
        alias, target = max(place_candidates, key=lambda item: len(item[0]))
        # Avoid treating unrelated sentences containing a city name as spiritual queries.
        if any(x in cleaned for x in (
            "temple", "temples", "god", "goddess", "holy", "spiritual", "pilgrimage", "darshan",
            "about", "tell me", "what is", "where is", "history", "story", "stories", "worship",
            "visit", "place", "sacred", "religious", "religion"
        )) or cleaned in place_aliases:
            speak(place_answers[target])
            return True

    if any(x in cleaned for x in ("darshan", "what is darshan", "meaning of darshan")):
        speak(
            "Darshan is a Sanskrit-derived term commonly used in Hindu and several Indian religious traditions for seeing and being in the presence "
            "of a deity, sacred person, or sacred object. In temple practice, devotees seek darshan as an act of worship and spiritual connection. "
            "The exact ritual and meaning can vary by tradition and place."
        )
        return True

    if any(x in cleaned for x in ("masjid", "mosque")) and any(x in cleaned for x in ("what is", "about", "tell me", "meaning", "place of worship")):
        speak(
            "A masjid, or mosque, is a place of worship for Muslims. Muslims gather there for prayer, especially the congregational Friday prayer, "
            "as well as for learning and community activities. The word masjid is Arabic and refers to a place of prostration in worship."
        )
        return True

    if "church" in cleaned or "churches" in cleaned:
        if any(x in cleaned for x in ("what is", "about", "tell me", "place of worship", "meaning")):
            speak(
                "A church is a Christian place of worship and community. Churches may host prayer, worship services, Bible reading, teaching, "
                "sacraments or ordinances depending on denomination, and community service. Christian churches differ in architecture, worship style, "
                "and theology."
            )
            return True

    if "gurdwara" in cleaned or "gurudwara" in cleaned:
        if any(x in cleaned for x in ("what is", "about", "tell me", "place of worship", "meaning")):
            speak(
                "A gurdwara is a place of worship and community in Sikhism. It is associated with the Guru Granth Sahib and commonly includes "
                "prayer, kirtan, community service, and langar, the free community meal."
            )
            return True

    # Gods/deities: longest name first. Require a spiritual question context so a
    # person's casual mention of a name is not automatically intercepted.
    god_candidates = [(alias, target) for alias, target in aliases.items() if alias in cleaned]
    spiritual_context = any(x in cleaned for x in (
        "god", "goddess", "lord", "deity", "about", "tell me", "who is", "what is", "explain", "story",
        "life", "teachings", "religion", "spiritual", "temple", "worship"
    ))
    if god_candidates and spiritual_context:
        alias, target = max(god_candidates, key=lambda item: len(item[0]))
        speak(god_answers[target])
        return True

    # General spiritual/religious knowledge requests. This is intentionally
    # narrow so Command 12 does not steal ordinary conversation from earlier commands.
    if any(x in cleaned for x in (
        "religion", "religious", "spirituality", "spiritual knowledge", "faith", "worship", "pilgrimage"
    )) and any(x in cleaned for x in ("what is", "about", "tell me", "explain", "meaning", "teach me")):
        speak(
            "I can provide offline spiritual and religious knowledge about deities and religious figures, holy books and scriptures, "
            "temples and places of worship, darshan, pilgrimage traditions, and spiritual stories. I will keep different religious traditions "
            "separate and describe beliefs respectfully."
        )
        return True

    # If a clearly religious keyword is present, give a useful offline fallback.
    religious_keywords = (
        "krishna", "rama", "shiva", "vishnu", "ganesha", "lakshmi", "saraswati", "durga", "parvati", "kamakshi",
        "kamakshamma", "chenchu", "hanuman", "venkateswara", "ayyappa", "subramanya", "subramanyam", "murugan",
        "narasimha", "buddha", "jesus", "allah", "gita", "ramayana", "mahabharata", "veda", "upanishad", "purana",
        "bible", "quran", "gurdwara", "masjid", "mosque", "church", "temple", "darshan"
    )
    if any(word in cleaned for word in religious_keywords):
        speak(
            "I have an offline spiritual knowledge center for gods and religious figures, holy books, temples and places of worship, "
            "darshan, and spiritual stories. Please ask a specific question such as 'Who is Lord Krishna?', 'What is the Bhagavad Gita?', "
            "'Tell me about Tirumala Tirupati Temple', or 'Tell me a Hanuman story.'"
        )
        return True

    return False


# ---------------------- Command 11: Offline Technology Knowledge Center ----------------------

def handle_command11(command):
    """
    Offline technology knowledge center.
    This handler contains its own knowledge and does not use web/API searches.
    """
    cleaned = normalize_command(command)
    cleaned = strip_assistant_address(cleaned)

    # Priority answers for Command 11 requested questions.
    # These are checked first so broad technology phrases cannot select a
    # shorter/generic answer. This block only adds Command 11 knowledge.
    priority_answers = {
        "what is the internet": (
            "The Internet is a worldwide system of interconnected computer networks "
            "that communicate using standardized protocols such as TCP/IP. It allows "
            "devices and services around the world to exchange data and access resources. "
            "The Internet supports services such as the World Wide Web, email, messaging, "
            "video calls, online banking, cloud services, streaming, and file sharing. "
            "The World Wide Web is one service that operates on the Internet; the Internet "
            "itself is the underlying global network infrastructure."
        ),
        "what is cloud computing": (
            "Cloud computing is the on-demand delivery of computing resources through "
            "remote data centers, usually over a network such as the Internet. These "
            "resources can include computing power, storage, databases, networking, "
            "security services, and software. Instead of purchasing and maintaining all "
            "the required hardware locally, an organization or user can obtain resources "
            "from a cloud provider and scale them as needed. Common cloud service models "
            "include Infrastructure as a Service, Platform as a Service, and Software as "
            "a Service. Cloud computing is widely used for websites, mobile applications, "
            "backup, data analytics, AI workloads, collaboration, and business systems."
        ),
        "tell me about cloud technology": (
            "Cloud technology is a group of technologies that deliver computing resources "
            "and digital services from remote data centers over a network. It can provide "
            "servers, storage, databases, networking, software platforms, security tools, "
            "and other services on demand. Important characteristics include resource "
            "sharing, rapid scaling, remote access, automation, and usage-based resource "
            "management. Cloud technology is used for websites, applications, online "
            "storage, business systems, data analytics, artificial intelligence, and "
            "disaster recovery. Examples of major cloud platforms include Amazon Web "
            "Services, Microsoft Azure, and Google Cloud."
        ),
        "what are the disadvantages of technology": (
            "Technology provides many benefits, but it also creates challenges. Important "
            "disadvantages can include privacy loss, cybersecurity threats, online fraud, "
            "misinformation, excessive screen use, digital addiction, social isolation in "
            "some situations, job disruption caused by automation, electronic waste, "
            "energy consumption, unequal access to technology, and dependence on complex "
            "digital systems. Technology itself is not automatically harmful; the impact "
            "depends on how it is designed, implemented, secured, and used."
        ),
        "what are the negative effects of technology": (
            "Negative effects of technology can include privacy and security risks, "
            "misinformation, cybercrime, excessive screen time, reduced physical activity, "
            "digital addiction, distraction, social and psychological pressures, job "
            "displacement in some occupations, electronic waste, and unequal access to "
            "digital resources. Responsible use, strong security, digital literacy, "
            "healthy screen habits, recycling, and appropriate policies can reduce many "
            "of these effects."
        ),
        "what are the advantages of technology": (
            "Technology can improve communication, education, healthcare, transportation, "
            "productivity, accessibility, scientific research, agriculture, manufacturing, "
            "and access to information. It can automate repetitive tasks, help people work "
            "from different locations, make services faster, support data-driven decisions, "
            "connect people across long distances, and enable new products and services. "
            "Its benefits depend on responsible design and effective use."
        ),
        "what are the benefits of technology": (
            "The benefits of technology include faster communication, easier access to "
            "information, improved education and healthcare, greater productivity, "
            "automation of repetitive work, better transportation and navigation, improved "
            "business operations, scientific discovery, digital financial services, and "
            "greater accessibility for many people. Technology can also create new careers "
            "and make useful services available at large scale."
        ),
        "what technology careers are available": (
            "Technology offers many career paths. Examples include software developer, "
            "web developer, mobile app developer, data analyst, data scientist, AI engineer, "
            "machine learning engineer, cloud engineer, cybersecurity analyst, network "
            "engineer, database administrator, DevOps engineer, UI or UX professional, "
            "robotics engineer, embedded systems engineer, semiconductor engineer, "
            "technical support specialist, systems administrator, and technology project "
            "manager. The best career depends on your interests, education, and the skills "
            "you develop."
        ),
        "what jobs are available in technology": (
            "Technology jobs include software development, web development, mobile app "
            "development, data analysis, data science, artificial intelligence, machine "
            "learning, cloud computing, cybersecurity, networking, database administration, "
            "DevOps, UI and UX design, robotics, embedded systems, semiconductor engineering, "
            "IT support, systems administration, and technical project management. Different "
            "roles require different combinations of programming, mathematics, communication, "
            "system, design, and problem-solving skills."
        ),
        "what are careers in technology": (
            "A career in technology can lead to roles such as software engineer, web "
            "developer, mobile developer, data scientist, data analyst, AI or ML engineer, "
            "cloud engineer, cybersecurity professional, network engineer, database "
            "administrator, DevOps engineer, robotics engineer, embedded systems engineer, "
            "UI or UX designer, semiconductor engineer, IT specialist, or technical project "
            "manager. A strong foundation in computer fundamentals, problem solving, and "
            "relevant tools can help you enter these fields."
        ),
        "how does technology help students": (
            "Technology helps students by providing access to digital textbooks, educational "
            "videos, online courses, simulations, virtual laboratories, programming tools, "
            "research resources, collaboration platforms, productivity software, and "
            "accessibility features. Students can use technology to practice skills, organize "
            "study materials, communicate with teachers and classmates, and learn subjects "
            "at their own pace. Technology should support learning rather than replace "
            "critical thinking, practical work, or verification of important information."
        ),
        "how does technology help businesses": (
            "Technology helps businesses communicate with customers and employees, automate "
            "repetitive work, manage finances and inventory, analyze data, operate websites "
            "and online stores, protect information, manage customers, support remote work, "
            "and improve production and logistics. Cloud services can provide scalable "
            "infrastructure, while analytics and AI can help organizations identify patterns "
            "and support decisions. Businesses must also manage cybersecurity, privacy, cost, "
            "reliability, and employee training."
        ),
        "what are future technologies": (
            "Important future-facing technology areas include artificial intelligence and "
            "generative AI, advanced robotics and automation, next-generation semiconductor "
            "technology, quantum computing, biotechnology, advanced materials, renewable "
            "energy technologies, autonomous systems, connected devices and IoT, cloud and "
            "edge computing, cybersecurity, advanced communications, and new human-computer "
            "interfaces. The exact future is uncertain, so these are major areas of research "
            "and development rather than guaranteed predictions."
        ),
        "what technology will shape the future": (
            "Several technology areas are likely to have major influence on the future, "
            "including artificial intelligence, robotics and automation, advanced "
            "semiconductors, cloud and edge computing, cybersecurity, connected devices, "
            "biotechnology, advanced materials, renewable-energy technologies, quantum "
            "computing, and advanced communication systems. Their impact will depend on "
            "technical progress, cost, safety, regulation, and how society adopts them."
        ),
        "what are the latest technology trends": (
            "I am answering in offline mode, so I cannot verify live technology news or "
            "today's exact trends. My offline knowledge identifies major technology trends "
            "and development areas such as generative AI, AI assistants and agents, "
            "specialized AI processors such as GPUs and NPUs, cloud and edge computing, "
            "cybersecurity, robotics and automation, connected devices, advanced "
            "semiconductors, biotechnology, quantum computing, and advanced communication "
            "systems. For truly latest developments, Sara would need an online information "
            "source."
        ),
        "list the future technologies": (
            "A useful list of future-facing technologies includes artificial intelligence "
            "and generative AI, robotics and automation, autonomous vehicles and drones, "
            "advanced semiconductor chips, quantum computing, biotechnology, nanotechnology, "
            "renewable-energy technologies, energy storage, cloud and edge computing, IoT, "
            "cybersecurity, advanced communication networks, augmented and mixed reality, "
            "and advanced human-computer interfaces. These are areas of ongoing research "
            "and development, not guarantees about exactly what the future will look like."
        ),
        "what is drone technology": (
            "Drone technology refers to unmanned aircraft systems that can fly without a "
            "person physically operating the aircraft from inside it. A drone typically "
            "combines a flight controller, motors and propellers, a battery, communication "
            "systems, sensors, navigation equipment, and software. Some drones are remotely "
            "piloted, while more advanced systems can automate parts of a flight using "
            "GPS, cameras, obstacle sensors, and onboard computing. Drones are used for "
            "photography, mapping, surveying, inspection, agriculture, emergency response, "
            "delivery research, environmental monitoring, and other specialized tasks."
        ),
        "how drone technology helps": (
            "Drone technology can help by collecting aerial information quickly and from "
            "areas that may be difficult, dangerous, or expensive for people to access. "
            "Drones can support crop monitoring, land surveying, mapping, infrastructure "
            "inspection, disaster assessment, environmental observation, photography, and "
            "search-and-rescue operations. They can reduce the time needed for some surveys "
            "and provide detailed images or sensor data. Safe operation, privacy, weather "
            "conditions, regulations, and battery limits must still be considered."
        ),
        "what the uses of drones": (
            "Drones are used for aerial photography and video, land surveying and mapping, "
            "agriculture, crop monitoring, infrastructure inspection, construction "
            "monitoring, environmental observation, disaster assessment, search and rescue, "
            "wildlife monitoring, traffic observation, scientific research, and some "
            "specialized delivery and logistics experiments. Different drone designs are "
            "suited to different tasks, so the equipment and sensors depend on the application."
        ),
        "what are the uses of drones": (
            "Drones are used for aerial photography and video, land surveying and mapping, "
            "precision agriculture, crop monitoring, infrastructure inspection, construction "
            "monitoring, environmental observation, disaster assessment, search and rescue, "
            "wildlife monitoring, scientific research, and specialized logistics or delivery "
            "applications. Cameras, thermal sensors, multispectral sensors, GPS, and other "
            "equipment can be added depending on the job."
        ),
        "how drone technology works for agriculture": (
            "In agriculture, drones can fly over fields and collect images or sensor data "
            "about crops and soil. Cameras can provide detailed visual images, while "
            "multispectral or other specialized sensors can reveal information that may not "
            "be obvious to the human eye. Farmers and agricultural specialists can analyze "
            "the data to identify crop stress, irrigation problems, weeds, disease patterns, "
            "growth differences, or areas that need closer inspection. Drones can also be "
            "used for mapping and, where legally permitted and appropriately equipped, "
            "targeted spraying. The main benefit is that aerial data can help farmers inspect "
            "large areas more efficiently and make more informed management decisions."
        ),
    }

    # Additional natural speech variants for the reported bug cases.
    priority_answers.update({
        "what is cloud computing": priority_answers["what is cloud computing"],
        "can you tell me about cloud computing": priority_answers["what is cloud computing"],
        "explain cloud computing": priority_answers["what is cloud computing"],
        "tell me about cloud computing": priority_answers["what is cloud computing"],
        "tell me about cloud technology": priority_answers["tell me about cloud technology"],
        "explain cloud technology": priority_answers["tell me about cloud technology"],
        "can you tell me about cloud technology": priority_answers["tell me about cloud technology"],
        "what technology careers are available": priority_answers["what technology careers are available"],
        "what careers are available in technology": priority_answers["what are careers in technology"],
        "what are careers in technology": priority_answers["what are careers in technology"],
    })

    exact_command = cleaned
    if exact_command in priority_answers:
        speak(priority_answers[exact_command])
        return True

    # Natural wording aliases.
    aliases = {
        "information technology": "it technology",
        "internet of things": "iot",
        "artificial intelligence": "artificial intelligence",
        "virtual reality": "virtual reality",
        "augmented reality": "augmented reality",
        "mixed reality": "mixed reality",
        "cloud computing": "cloud computing",
        "cyber security": "cybersecurity",
        "cyber security technology": "cybersecurity",
        "5 g": "5g",
        "five g": "5g",
        "machine learning": "machine learning",
        "generative artificial intelligence": "generative ai",
        "generative ai": "generative ai",
    }
    for old, new in aliases.items():
        cleaned = cleaned.replace(old, new)

    technology_words = (
        "technology", "technologies", "tech", "digital", "computer",
        "software", "hardware", "internet", "cloud", "iot", "robotics",
        "robot", "automation", "blockchain", "5g", "semiconductor",
        "quantum", "biotechnology", "nanotechnology", "cybersecurity",
        "cybersecurity", "cyber", "virtual reality", "augmented reality",
        "mixed reality", "artificial intelligence", "machine learning",
        "generative ai", "npu", "processor", "microprocessor", "drone", "drones",
        "drone technology"
    )

    # Do not capture ordinary weather conversation merely because it contains
    # the word "cloud". A standalone "cloud"/"cloudy" belongs to weather;
    # cloud technology must have an explicit technology/computing context.
    cloud_tech_context = (
        "cloud computing" in cleaned
        or "cloud technology" in cleaned
        or "cloud service" in cleaned
        or "cloud services" in cleaned
        or "cloud storage" in cleaned
        or "cloud platform" in cleaned
        or "cloud platforms" in cleaned
    )
    technology_terms_without_standalone_cloud = tuple(
        term for term in technology_words if term not in {"cloud"}
    )
    has_technology_topic = (
        cloud_tech_context
        or any(term in cleaned for term in technology_terms_without_standalone_cloud)
    )
    if not has_technology_topic:
        return False

    answers = [
        (("what is technology", "define technology", "meaning of technology",
          "tell me about technology", "explain technology"),
         "Technology is the practical use of scientific knowledge, engineering, tools, systems, and methods to solve problems or achieve useful goals. It includes physical products such as computers and machines as well as software, networks, digital services, and industrial processes. Technology is used in education, healthcare, transportation, communication, manufacturing, agriculture, finance, entertainment, and many other areas."),

        (("types of technology", "different types of technology",
          "what are the types of technology"),
         "Major areas of technology include information technology, communication technology, computer technology, software technology, hardware technology, cloud computing, artificial intelligence, robotics and automation, Internet of Things, cybersecurity, biotechnology, nanotechnology, semiconductor technology, blockchain, quantum computing, and digital media. These areas often overlap and work together."),

        (("what is information technology", "what is it technology",
          "define information technology", "what does it mean by it"),
         "Information Technology, or IT, is the use of computers, software, networks, databases, and digital systems to create, store, process, protect, and exchange information. IT is used in businesses, schools, hospitals, banks, governments, and almost every modern organization. Common IT careers include software development, system administration, networking, database administration, cloud engineering, cybersecurity, and IT support."),

        (("what is computer technology", "computer technology",
          "tell me about computer technology"),
         "Computer technology covers the hardware and software systems used to process information. Hardware includes processors, memory, storage, displays, input devices, and networking components. Software includes operating systems, applications, drivers, and development tools. Modern computer technology also includes cloud computing, artificial intelligence, specialized accelerators, and connected devices."),

        (("what is digital technology", "digital technology",
          "tell me about digital technology"),
         "Digital technology represents information using digital signals, normally binary data, and processes that information using electronic systems. Computers, smartphones, digital cameras, online services, digital payments, streaming platforms, and modern communication systems are examples. Digital technology makes it possible to store, process, transmit, and automate large amounts of information efficiently."),

        (("what is communication technology", "communication technology"),
         "Communication technology consists of tools and systems used to exchange information between people and devices. Examples include mobile networks, Wi-Fi, fiber-optic communication, satellites, Bluetooth, email, messaging systems, video conferencing, and internet services. It has made real-time global communication possible."),

        (("what is cloud computing", "cloud technology", "tell me about cloud computing",
          "what is cloud technology"),
         "Cloud computing is the delivery of computing resources such as servers, storage, databases, networking, and software through remote data centers, commonly over the internet. Users can obtain resources when needed instead of owning all of the underlying infrastructure. Common cloud service models include infrastructure as a service, platform as a service, and software as a service. Cloud computing is widely used for websites, applications, backups, data analytics, and artificial intelligence."),

        (("what is internet of things", "what is iot", "define iot",
          "tell me about iot", "explain internet of things"),
         "IoT stands for Internet of Things. It refers to physical objects that contain sensors, software, processing capability, and network connectivity so they can collect and exchange data. Examples include smart watches, smart home devices, industrial sensors, connected vehicles, medical devices, and smart agriculture systems. IoT can support monitoring, automation, predictive maintenance, and resource management."),

        (("what is blockchain", "blockchain technology", "tell me about blockchain"),
         "Blockchain is a distributed digital ledger technology in which records are organized into linked blocks and protected using cryptographic techniques. Copies of the ledger can be maintained across a network of participants. Blockchain can provide tamper-evident records and is used in areas such as cryptocurrencies, asset tracking, digital identity experiments, and certain supply-chain applications. Not every application needs blockchain; traditional databases can be more suitable for many systems."),

        (("what is 5g", "5g technology", "tell me about 5g"),
         "5G is a generation of mobile communication technology designed to provide higher data rates, lower latency, greater capacity, and support for many connected devices compared with earlier generations. Its practical performance depends on spectrum, network design, device capability, and local conditions. 5G supports applications such as high-speed mobile broadband, industrial connectivity, connected devices, and some low-latency use cases."),

        (("what is robotics", "robotics technology", "tell me about robotics",
          "what are robots"),
         "Robotics is the field of engineering and computer science concerned with designing, building, programming, controlling, and operating robots. Robots can use sensors to perceive their environment, processors and software to make decisions, and actuators to perform actions. Robotics is used in manufacturing, logistics, healthcare, agriculture, exploration, education, and domestic applications."),

        (("what is automation", "automation technology", "tell me about automation"),
         "Automation is the use of technology to perform tasks with reduced human intervention. It can involve software, control systems, sensors, machines, robots, or combinations of them. Examples include automated manufacturing lines, software workflows, industrial control systems, automated testing, and robotic process automation. Good automation can improve consistency and efficiency, but it still requires appropriate design, monitoring, safety controls, and maintenance."),

        (("what is semiconductor technology", "what are semiconductors",
          "tell me about semiconductor technology"),
         "Semiconductors are materials whose electrical properties can be controlled and used to build electronic devices. Silicon is the most widely used semiconductor material. Semiconductor technology enables transistors, integrated circuits, memory, processors, sensors, communication chips, and many other electronic components. Modern computing, smartphones, vehicles, networking equipment, and artificial intelligence hardware depend heavily on semiconductor technology."),

        (("what is quantum computing", "quantum technology", "tell me about quantum computing"),
         "Quantum computing is a computing approach based on quantum-mechanical principles. Instead of using only classical bits, quantum computers use quantum bits, or qubits, whose states can exhibit properties such as superposition and entanglement. Quantum algorithms can provide major advantages for certain specialized problems, but quantum computers are still difficult to build and operate reliably. They are not a universal replacement for ordinary computers."),

        (("what is biotechnology", "biotechnology technology", "tell me about biotechnology"),
         "Biotechnology applies biological systems, organisms, cells, or biological molecules to develop useful products and processes. Examples include vaccines, medicines, diagnostic methods, improved crops, industrial enzymes, and some forms of genetic engineering. Biotechnology combines biology with fields such as chemistry, medicine, engineering, and data science."),

        (("what is nanotechnology", "tell me about nanotechnology"),
         "Nanotechnology involves understanding and controlling matter at extremely small scales, commonly around one to one hundred nanometers for many applications. At these scales, materials can show useful electrical, optical, chemical, or mechanical properties. Nanotechnology is researched for medicine, electronics, materials, energy, sensors, and manufacturing."),

        (("what is cybersecurity", "what is cyber security", "cybersecurity technology",
          "tell me about cybersecurity"),
         "Cybersecurity is the practice of protecting computers, networks, applications, devices, and data from unauthorized access, disruption, damage, and misuse. Important areas include authentication, access control, encryption, secure software development, network security, monitoring, vulnerability management, backups, incident response, and security awareness. Cybersecurity is important for individuals, businesses, governments, and critical infrastructure."),

        (("what is virtual reality", "what is vr", "tell me about virtual reality"),
         "Virtual Reality, or VR, is a technology that creates an interactive computer-generated environment that a person can experience through a headset and other input devices. VR can track movement and provide visual and sometimes audio feedback. It is used in gaming, training, simulation, education, design, therapy, and virtual experiences."),

        (("what is augmented reality", "what is ar", "tell me about augmented reality"),
         "Augmented Reality, or AR, adds computer-generated information or objects to a person's view of the real world. Smartphones, tablets, smart glasses, and other devices can be used for AR. Applications include navigation, education, industrial assistance, retail visualization, maintenance, and entertainment."),

        (("what is mixed reality", "tell me about mixed reality"),
         "Mixed Reality combines physical and digital environments so that digital objects can appear to interact with the real environment. It generally uses spatial sensing and tracking to place digital content in a stable relationship with physical surroundings. Mixed reality can be useful for training, design, collaboration, education, and visualization."),

        (("what is artificial intelligence technology", "ai technology",
          "what is ai technology"),
         "Artificial Intelligence is a field of computing focused on building systems that can perform tasks that normally require aspects of human intelligence, such as recognizing patterns, understanding language, making predictions, planning, or generating content. Modern AI commonly uses machine learning, neural networks, data, algorithms, and specialized computing hardware. Applications include assistants, recommendation systems, computer vision, language systems, robotics, and scientific analysis."),

        (("what is machine learning technology", "machine learning technology"),
         "Machine Learning is a branch of artificial intelligence in which algorithms learn patterns from data and use those patterns to make predictions, classifications, or decisions. Common approaches include supervised learning, unsupervised learning, and reinforcement learning. Machine learning is used in fraud detection, recommendations, forecasting, computer vision, natural language processing, healthcare research, and many other applications."),

        (("what is generative ai", "generative ai technology",
          "tell me about generative ai"),
         "Generative AI refers to AI systems that can create new content such as text, images, audio, video, or software code from learned patterns and a user's instructions. Large language models are a major example for text and code. Generative AI can support education, writing, programming, design, research, and productivity, but its output should be checked because AI systems can produce incorrect, incomplete, biased, or fabricated information."),

        (("what is npu", "what is neural processing unit",
          "neural processing unit", "npu technology"),
         "NPU stands for Neural Processing Unit. It is a processor or accelerator designed to efficiently run certain artificial intelligence and machine learning workloads, especially neural-network operations. NPUs can improve performance and energy efficiency for supported AI tasks on devices such as laptops, smartphones, and other edge devices. The actual benefit depends on the software, model, drivers, and hardware implementation."),

        (("what is processor technology", "what is a processor",
          "tell me about processors"),
         "A processor, or central processing unit, executes instructions and performs calculations that allow software to run. Modern systems may also include specialized processors such as GPUs for highly parallel workloads and NPUs for certain AI workloads. Processor performance depends on factors such as architecture, clock behavior, number of cores, cache, power limits, memory, software optimization, and the workload."),

        (("advantages of technology", "benefits of technology",
          "how does technology help"),
         "Technology can improve communication, education, healthcare, productivity, transportation, accessibility, scientific research, and access to information. It can automate repetitive work, connect people across distances, enable new services, and help analyze large amounts of data. The benefits depend on how technology is designed and used."),

        (("disadvantages of technology", "problems with technology",
          "negative effects of technology"),
         "Technology can also create challenges such as privacy risks, cybersecurity threats, misinformation, excessive screen use, digital addiction, job disruption, electronic waste, unequal access, and dependence on complex systems. Responsible design, security, education, regulation, and balanced use can reduce many of these risks."),

        (("technology for students", "how technology helps students",
          "technology help education", "technology in education"),
         "Technology can help students access digital textbooks, educational videos, simulations, programming environments, online courses, collaboration tools, accessibility features, and research resources. It can also support personalized practice and productivity. Students should still verify important information and develop independent thinking rather than depending entirely on technology."),

        (("technology in business", "how technology helps businesses",
          "technology for business"),
         "Businesses use technology for communication, accounting, customer management, online sales, data analysis, cybersecurity, automation, cloud services, software development, manufacturing, and decision support. Technology can reduce repetitive work and improve access to information, but organizations must also manage security, privacy, costs, reliability, and employee training."),

        (("technology careers", "technology jobs", "careers in technology",
          "jobs in technology", "technology career options"),
         "Technology offers many career paths, including software developer, web developer, mobile app developer, data analyst, data scientist, AI engineer, machine learning engineer, cloud engineer, cybersecurity analyst, network engineer, database administrator, DevOps engineer, UI and UX professional, robotics engineer, embedded systems engineer, and technical support specialist. The best path depends on your interests and the skills you build."),

        (("future technology", "future technologies", "technology of the future",
          "what technologies will shape the future"),
         "Important technology areas likely to remain significant include artificial intelligence, robotics and automation, advanced semiconductors, cloud and edge computing, cybersecurity, connected devices, renewable-energy technologies, biotechnology, advanced materials, and quantum computing. The exact future is uncertain, so these should be treated as major technology areas rather than guaranteed predictions."),

        (("latest technology trends", "new technology trends",
          "recent technology trends", "current technology trends"),
         "I am answering in offline mode, so I cannot verify live or current technology news. My offline knowledge can explain major technology trends such as artificial intelligence, generative AI, specialized AI processors, cloud and edge computing, cybersecurity, robotics, connected devices, advanced semiconductors, biotechnology, and quantum computing."),
    ]

    # Longest phrase wins. This prevents broad terms from overriding
    # specific topics such as "cloud computing" or "machine learning".
    best_answer = None
    best_length = -1
    for phrases, answer in answers:
        for phrase in phrases:
            phrase = normalize_command(phrase)
            if phrase in cleaned:
                length = len(phrase.split())
                if length > best_length:
                    best_length = length
                    best_answer = answer

    if best_answer:
        speak(best_answer)
        return True

    # Generic technology question fallback.
    if any(word in cleaned for word in ("technology", "technologies", "tech")):
        speak("Technology is a broad field that includes computing, software, hardware, networks, artificial intelligence, communication, automation, robotics, cybersecurity, cloud computing, and many other areas. Ask me about a specific technology and I can explain it in offline mode.")
        return True

    return False


# ---------------------- Command 10: Offline Programming + Data Science + Jobs ----------------------
def handle_command10(command):
    """Command 10: self-contained offline knowledge center for programming languages,
    data science, and jobs/careers associated with programming languages.

    No web request is made by this handler. It is intentionally separate from
    Commands 1-9 so existing working behavior is preserved.
    """
    raw = normalize_command(command or "")
    if not raw:
        return False

    cleaned = re.sub(r"[^a-z0-9 ]", " ", raw.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\bprograming\b", "programming", cleaned)
    cleaned = re.sub(r"\bdata scince\b", "data science", cleaned)
    cleaned = re.sub(r"\bdatascience\b", "data science", cleaned)

    # Language aliases commonly produced by speech recognition.
    aliases = {
        "py": "python", "python language": "python",
        "js": "javascript", "java script": "javascript",
        "ts": "typescript", "type script": "typescript",
        "cpp": "c++", "c plus plus": "c++", "c plusplus": "c++",
        "c sharp": "c#", "c hash": "c#",
        "golang": "go", "r language": "r",
        "sql language": "sql", "php language": "php",
    }
    for old, new in aliases.items():
        cleaned = re.sub(rf"\b{re.escape(old)}\b", new, cleaned)

    language_names = {
        "python", "java", "c", "c++", "c#", "javascript", "typescript",
        "go", "rust", "swift", "kotlin", "r", "sql", "php"
    }
    language_present = any(re.search(rf"\b{re.escape(lang)}\b", cleaned) for lang in language_names)

    data_words = {
        "data science", "data scientist", "data scientists", "datascience",
        "data analysis", "data analyst", "data analytics", "data engineer",
        "data engineering", "pandas", "numpy", "scikit learn", "statistics",
        "machine learning", "data visualization", "jupyter", "power bi", "tableau"
    }
    job_words = {
        "job", "jobs", "career", "careers", "salary", "salaries", "role", "roles",
        "employment", "work", "profession", "professions", "opportunities", "job options",
        "career options", "which job", "what job", "what jobs"
    }
    programming_words = {
        "programming", "programming language", "programming languages", "coding",
        "code", "developer", "developers", "software development", "software engineer",
        "language", "languages", "learn programming", "learn coding"
    }

    has_data = any(w in cleaned for w in data_words)
    has_job = any(w in cleaned for w in job_words)
    has_programming = any(w in cleaned for w in programming_words)

    # Command 10 should only claim questions that clearly belong to its topic.
    # A bare "what is python" is included because the language itself is explicit.
    if not (language_present or has_data or has_programming or (has_job and language_present)):
        return False

    answers = [
        # ---------------- Programming basics ----------------
        ((
            "what is programming", "what is programming language", "what are programming languages",
            "meaning of programming language", "programming language meaning", "what is coding",
        ),
         "A programming language is a way for people to write instructions that computers can execute. Different languages are designed for different kinds of work. Python is popular for AI and data science, Java and C sharp are common in application and enterprise development, C and C plus plus are common in systems and performance-focused software, JavaScript and TypeScript are important for web applications, and SQL is used to work with relational databases."),

        ((
            "which programming language should i learn", "which programming language should i learn first",
            "best programming language to learn", "which language is best to learn",
            "which programming language is best", "best language for beginners",
        ),
         "For a beginner, Python is a strong first choice because its syntax is relatively easy to read and it is useful in software development, automation, AI and data science. JavaScript or TypeScript is a strong choice for web development. C or C plus plus is useful for systems and performance-focused programming. The best first language depends on the career goal."),

        ((
            "python", "what is python", "about python", "python uses", "uses of python",
            "why learn python", "python programming",
        ),
         "Python is a general-purpose programming language known for readable syntax and a large ecosystem. It is widely used for web development, automation, scripting, data analysis, data science, machine learning, AI, testing and scientific computing. Useful libraries include NumPy, pandas, scikit-learn, PyTorch and TensorFlow."),

        ((
            "java", "what is java", "about java", "java uses", "uses of java",
            "why learn java", "java programming",
        ),
         "Java is a general-purpose, object-oriented language used widely in enterprise software, backend services, Android development historically and in many large systems. It is known for portability through the Java Virtual Machine and has a large ecosystem."),

        ((
            "c plus plus", "c++", "what is c++", "about c++", "c++ uses", "uses of c++",
            "why learn c++", "c plus plus programming",
        ),
         "C plus plus is a high-performance language used for systems software, game engines, graphics, embedded systems, desktop software and performance-sensitive applications. It gives programmers detailed control over memory and system resources."),

        ((
            "what is c", "about c", "c uses", "uses of c", "why learn c", "c programming",
        ),
         "C is a procedural systems programming language used in operating systems, embedded systems, firmware, compilers and other software where low-level control and predictable performance are important."),

        ((
            "c sharp", "c#", "what is c#", "about c#", "c# uses", "uses of c#",
            "why learn c#", "c sharp programming",
        ),
         "C sharp is a modern language in the .NET ecosystem. It is used for web backends with ASP.NET, desktop applications, enterprise software, cloud services and game development with engines such as Unity."),

        ((
            "javascript", "java script", "what is javascript", "about javascript",
            "javascript uses", "uses of javascript", "why learn javascript",
        ),
         "JavaScript is a major language for web development. It runs in browsers and can also run on servers through environments such as Node.js. It is used for interactive websites, web applications, APIs and full-stack development."),

        ((
            "typescript", "type script", "what is typescript", "about typescript",
            "typescript uses", "uses of typescript", "why learn typescript",
        ),
         "TypeScript is a superset of JavaScript that adds static typing and other development features. It is widely used for large web applications, frontend development, backend services and full-stack projects where stronger tooling can improve maintainability."),

        ((
            "what is go", "about go", "go uses", "uses of go", "golang", "why learn go",
        ),
         "Go, also called Golang, is designed for simple, efficient software and strong concurrency support. It is commonly used for cloud services, backend systems, networking tools, command-line programs and infrastructure software."),

        ((
            "rust", "what is rust", "about rust", "rust uses", "uses of rust", "why learn rust",
        ),
         "Rust is a systems programming language focused on performance and memory safety. It is useful for systems software, command-line tools, networking, embedded work, WebAssembly and performance-sensitive applications."),

        ((
            "swift", "what is swift", "about swift", "swift uses", "uses of swift", "why learn swift",
        ),
         "Swift is Apple's programming language for building applications across Apple platforms such as iOS, iPadOS, macOS, watchOS and visionOS. It is designed for safety, performance and modern application development."),

        ((
            "kotlin", "what is kotlin", "about kotlin", "kotlin uses", "uses of kotlin", "why learn kotlin",
        ),
         "Kotlin is a modern statically typed language used heavily for Android development and also for backend and multiplatform applications. It works well with the Java ecosystem and emphasizes concise, expressive code."),

        ((
            "r language", "what is r", "about r", "r uses", "uses of r", "why learn r",
        ),
         "R is a programming language and environment especially useful for statistics, data analysis and data visualization. It is popular in statistical research and analytics and has packages for many data-science workflows."),

        ((
            "sql", "what is sql", "about sql", "sql uses", "uses of sql", "why learn sql",
        ),
         "SQL, or Structured Query Language, is used to store, query, update and analyze data in relational database systems. SQL is an important skill for data analysts, data scientists, data engineers, backend developers and many software engineers."),

        ((
            "php", "what is php", "about php", "php uses", "uses of php", "why learn php",
        ),
         "PHP is a server-side scripting language widely used for web development. It can power dynamic websites and backend applications and is used in many content-management systems and web-hosting environments."),

        # ---------------- Language-based jobs ----------------
        ((
            "what jobs can i get with python", "what jobs can i get using python",
            "python jobs", "python job opportunities", "python career options",
            "career options with python", "jobs by python",
        ),
         "Python can lead to roles such as Python developer, backend developer, automation developer, data analyst, data scientist, machine-learning engineer, AI engineer, test automation engineer, DevOps or tooling developer, and research or scientific programmer. The job you qualify for also depends on databases, frameworks, cloud skills, projects and other supporting skills."),

        ((
            "what jobs can i get with java", "java jobs", "java career options",
            "career options with java", "jobs by java",
        ),
         "Java can lead to roles such as Java developer, backend developer, enterprise software developer, Android developer, API developer, cloud application developer, software engineer and test automation engineer."),

        ((
            "what jobs can i get with c++", "c++ jobs", "c plus plus jobs", "c++ career options",
            "career options with c++", "jobs by c++",
        ),
         "C plus plus can lead to roles such as systems programmer, C plus plus developer, game developer, graphics programmer, embedded software engineer, robotics software engineer, high-performance computing developer and desktop or application software engineer."),

        ((
            "what jobs can i get with c", "c jobs", "c career options", "career options with c", "jobs by c",
        ),
         "C can lead to roles such as embedded systems developer, firmware engineer, systems programmer, operating-system or low-level software developer, device-software engineer and microcontroller programmer."),

        ((
            "what jobs can i get with c#", "c# jobs", "c sharp jobs", "c# career options",
            "career options with c#", "jobs by c#",
        ),
         "C sharp can lead to roles such as .NET developer, C sharp developer, ASP.NET backend developer, enterprise software engineer, desktop application developer, cloud application developer and Unity game developer."),

        ((
            "what jobs can i get with javascript", "javascript jobs", "javascript career options",
            "career options with javascript", "jobs by javascript",
        ),
         "JavaScript can lead to roles such as frontend developer, web developer, full-stack developer, Node.js backend developer, UI engineer, web application engineer and JavaScript test automation developer."),

        ((
            "what jobs can i get with typescript", "typescript jobs", "typescript career options",
            "career options with typescript", "jobs by typescript",
        ),
         "TypeScript can lead to frontend developer, full-stack developer, web application engineer, Node.js backend developer and software engineer roles. It is especially useful when building larger JavaScript-based applications."),

        ((
            "what jobs can i get with go", "go jobs", "golang jobs", "go career options", "career options with go",
        ),
         "Go can lead to backend engineer, cloud software engineer, infrastructure developer, DevOps or platform engineer, networking software developer and distributed-systems developer roles."),

        ((
            "what jobs can i get with rust", "rust jobs", "rust career options", "career options with rust",
        ),
         "Rust can lead to systems programmer, backend developer, infrastructure developer, embedded software engineer, security-focused software developer, networking developer and WebAssembly developer roles."),

        ((
            "what jobs can i get with swift", "swift jobs", "swift career options", "career options with swift",
        ),
         "Swift can lead to iOS developer, macOS developer, Apple-platform software engineer and mobile application developer roles."),

        ((
            "what jobs can i get with kotlin", "kotlin jobs", "kotlin career options", "career options with kotlin",
        ),
         "Kotlin can lead to Android developer, backend developer, JVM software engineer, mobile application developer and Kotlin multiplatform developer roles."),

        ((
            "what jobs can i get with r", "r jobs", "r career options", "career options with r",
        ),
         "R is useful for roles such as data analyst, statistician, statistical programmer, data scientist, research analyst and biostatistics or research-focused roles, depending on the industry and qualifications."),

        ((
            "what jobs can i get with sql", "sql jobs", "sql career options", "career options with sql",
        ),
         "SQL is a core skill for data analyst, business intelligence analyst, data engineer, database developer, database administrator, backend developer and data scientist roles. SQL is usually combined with other skills rather than used alone."),

        ((
            "what jobs can i get with php", "php jobs", "php career options", "career options with php",
        ),
         "PHP can lead to PHP developer, backend web developer, full-stack web developer, CMS developer and web application developer roles."),

        ((
            "which programming language has more jobs", "which language has more jobs", "best programming language for jobs",
            "which programming language is best for jobs", "which language is best for career",
        ),
         "There is no single programming language that guarantees the most jobs everywhere. Python is broadly useful across software, automation, AI and data; Java is strong in enterprise and backend systems; JavaScript and TypeScript are important for web development; C sharp is strong in the .NET ecosystem; and C plus plus is valuable for systems, games and performance-focused software. Job demand varies by country, company and industry."),

        # ---------------- Data science ----------------
        ((
            "what is data science", "define data science", "meaning of data science", "about data science",
        ),
         "Data science is the practice of using data, statistics, programming and analytical or machine-learning methods to understand data, find patterns, make predictions and support decisions. A typical workflow includes collecting data, cleaning it, exploring it, analyzing it, building models when appropriate, evaluating results and communicating findings."),

        ((
            "what programming languages are used in data science", "which languages are used in data science",
            "programming languages for data science", "best language for data science", "language used in data science",
        ),
         "Python and R are major programming languages for data science. SQL is essential for working with relational databases. Python is especially common because of libraries such as NumPy, pandas, scikit-learn, Matplotlib and other machine-learning tools. R is strong for statistics and visualization. Other languages can be useful for specialized systems."),

        ((
            "data science tools", "tools used in data science", "what tools are used in data science",
            "data science software", "data science technologies",
        ),
         "Common data-science tools include Python, Jupyter Notebook, NumPy, pandas, Matplotlib, scikit-learn, SQL, R, RStudio, Git and spreadsheet tools. For dashboards and business intelligence, tools such as Power BI and Tableau are commonly used. The exact stack depends on the role and organization."),

        ((
            "data science roadmap", "roadmap to become a data scientist", "how to become a data scientist",
            "how can i learn data science", "learn data science",
        ),
         "A practical data-science roadmap is: learn Python and SQL; learn basic mathematics and statistics; learn NumPy and pandas; practise data cleaning and exploratory analysis; learn visualization; study scikit-learn and machine learning; learn how to evaluate models; build real projects; use Git and write clear documentation; then learn specialized areas such as deep learning, NLP or time-series analysis if your target role needs them. Build a portfolio that shows your reasoning, not only final charts."),

        ((
            "data science jobs", "data science career options", "careers in data science",
            "jobs in data science", "what jobs are in data science", "what jobs can i get in data science",
        ),
         "Data-science-related careers include data scientist, data analyst, business intelligence analyst, machine-learning engineer, data engineer, analytics engineer, statistician, research analyst, machine-learning researcher and data visualization specialist. The required skills differ between roles."),

        ((
            "data scientist skills", "skills for data scientist", "what skills are needed for data science",
        ),
         "Important data-science skills include Python or R, SQL, statistics, probability, data cleaning, exploratory analysis, visualization, machine learning, model evaluation, communication and problem solving. Git and basic software-engineering practices are also useful."),

        ((
            "data science projects", "projects for data science", "data science project ideas",
        ),
         "Good beginner data-science projects include sales analysis, student-performance analysis, customer segmentation, house-price analysis, movie or product recommendation experiments, sentiment analysis and time-series forecasting. A strong project should explain the question, data preparation, analysis, evaluation, limitations and conclusions."),

        ((
            "difference between data science and data analysis", "data science vs data analysis",
            "data analyst vs data scientist",
        ),
         "Data analysis often focuses on understanding existing data, producing reports, dashboards and actionable insights. Data science can include those activities plus statistical modeling, machine learning, prediction and more advanced experimentation. The boundary varies between organizations."),

        ((
            "data science and ai", "how data science is used in ai", "data science uses in ai",
            "how can data science help ai",
        ),
         "Data science supports AI by collecting and preparing data, exploring patterns, creating useful features, measuring data quality, building and evaluating models, and analyzing model results. Good AI systems depend heavily on suitable data and careful evaluation."),

        # ---------------- Cross-topic career guidance ----------------
        ((
            "programming language jobs", "jobs by programming language", "language based jobs",
            "programming language based jobs", "career by programming language",
            "which jobs are based on programming languages",
        ),
         "Programming-language-based careers include software developer, web developer, mobile developer, backend engineer, frontend engineer, data analyst, data scientist, AI or machine-learning engineer, embedded engineer, systems programmer, game developer, database developer and DevOps or platform engineer. The language is only one part of employability; projects, problem solving, databases, tools and communication skills also matter."),

        ((
            "programming language roadmap", "roadmap to become a programmer", "how to become a programmer",
            "how can i learn programming",
        ),
         "A general programming roadmap is: choose one language for your target, learn variables and data types, conditions and loops, functions, collections, error handling and modules, then learn object-oriented or functional concepts as appropriate. Next practise data structures and algorithms, Git, debugging, testing, APIs and databases. Build projects and gradually specialize in a career area."),

        ((
            "best language for data analyst", "language for data analyst", "programming language for data analyst",
        ),
         "For data analysts, SQL is essential, while Python or R can add strong analysis and automation skills. Spreadsheet tools and business-intelligence tools such as Power BI or Tableau are also useful depending on the job."),

        ((
            "best language for data scientist", "language for data scientist", "programming language for data scientist",
        ),
         "Python is a strong general choice for data science because it combines data handling, visualization and machine-learning libraries. R is also an excellent choice for statistics and analysis, and SQL is an essential supporting skill."),
    ]

    # Explicit coverage for broad or combined questions about machine learning
    # and programming languages, including natural phrasing such as "tell me about...".
    if "machine learning" in cleaned and any(term in cleaned for term in ("programming language", "programming languages", "which language", "languages used", "language used")):
        speak("Machine learning is a branch of artificial intelligence where models learn patterns from data to make predictions or classifications. Common programming languages for machine learning include Python, widely used with scikit-learn, PyTorch and TensorFlow; R for statistics; and Java, C plus plus or JavaScript for particular production, performance or web needs. For a beginner, start with Python, learn basic programming and statistics, then practise with small data projects.")
        return True

    if "machine learning" in cleaned and any(term in cleaned for term in ("about", "explain", "tell me", "what is", "meaning", "uses", "use of", "how does", "how is")):
        speak("Machine learning is a branch of artificial intelligence in which a computer model learns patterns from examples in data instead of relying only on hand-written rules. It can make predictions, classify information, recommend items, recognize speech or images, and forecast trends. The main approaches include supervised learning, unsupervised learning and reinforcement learning. Beginners can start with Python, basic statistics and small projects using scikit-learn.")
        return True

    if any(term in cleaned for term in ("programming languages", "programming language")) and any(term in cleaned for term in ("about", "explain", "tell me", "what are", "list", "types of")):
        speak("Programming languages are used to write instructions that computers can execute. Python is widely used for automation, AI and data science; Java and C sharp for many applications and backend systems; JavaScript and TypeScript for web development; C and C plus plus for systems and performance-focused software; and SQL for working with databases. A beginner interested in AI or data science can start with Python.")
        return True

    # Specific phrases win over broad phrases. Score the actual matched phrase.
    best_answer = None
    best_match_length = -1
    for phrases, answer in answers:
        for phrase in phrases:
            phrase_clean = phrase.lower().replace("c plus plus", "c++").replace("c sharp", "c#")
            if phrase_clean in cleaned:
                length = len(phrase_clean.split())
                if length > best_match_length:
                    best_match_length = length
                    best_answer = answer

    if best_answer is not None:
        speak(best_answer)
        return True

    # Topic-specific fallback keeps Command 10 useful without pretending that
    # an exact fact exists in the built-in database.
    if has_data:
        speak("I have an offline data-science knowledge center covering Python, R, SQL, statistics, data analysis, visualization, machine learning, tools, roadmaps, projects and careers. Please ask a specific data-science question.")
        return True
    if language_present or has_programming:
        speak("I have an offline programming-language knowledge center covering Python, Java, C, C plus plus, C sharp, JavaScript, TypeScript, Go, Rust, Swift, Kotlin, R, SQL and PHP, including uses and related careers. Please ask a specific language question.")
        return True
    return False

# ---------------------- Command 13: GPS, Live Location & WhatsApp Sharing ----------------------
# Command 13: current GPS/location, area-district-state-country, live tracking,
# and WhatsApp location preparation. No covert tracking is performed.

import asyncio
import subprocess
import difflib
import threading
import time
import webbrowser

# Windows 10/11 modern location API. This is the preferred provider for
# Command 13 because System.Device.Location is a legacy provider.
#
# V7 removes the two direct Foundation/Collections imports that caused the
# Pylance errors. If the PyWinRT Foundation/Collections projections are missing, Sara tries
# to install the required packages into the SAME Python environment that is
# running Sara, then imports the location API again.
WINRT_LOCATION_AVAILABLE = False
WINRT_LOCATION_IMPORT_ERROR = ""
_winrt_geolocation = None


def _load_winrt_location_support():
    global WINRT_LOCATION_AVAILABLE
    global WINRT_LOCATION_IMPORT_ERROR
    global _winrt_geolocation

    if os.name != "nt":
        WINRT_LOCATION_IMPORT_ERROR = "Windows only"
        return False

    try:
        # Windows.Devices.Geolocation automatically loads its required
        # Foundation and Foundation.Collections projections. We do not import
        # those child namespaces directly because Pylance may flag them even
        # when the geolocation package is installed correctly.
        import importlib
        _winrt_geolocation = importlib.import_module(
            "winrt.windows.devices.geolocation"
        )
        WINRT_LOCATION_AVAILABLE = True
        WINRT_LOCATION_IMPORT_ERROR = ""
        return True
    except Exception as first_error:
        first_details = str(first_error) or repr(first_error)
        print("WINRT LOCATION SUPPORT MISSING:", first_details)

    packages = [
        "winrt-Windows.Foundation",
        "winrt-Windows.Foundation.Collections",
        "winrt-Windows.Devices.Geolocation",
    ]
    try:
        print("Installing Windows location support into Sara's current Python environment...")
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", *packages],
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "pip installation failed").strip()
            WINRT_LOCATION_IMPORT_ERROR = details[-2000:]
            print("WINRT LOCATION INSTALL ERROR:", WINRT_LOCATION_IMPORT_ERROR)
            return False

        import importlib
        importlib.invalidate_caches()
        # Windows.Devices.Geolocation automatically loads its required
        # Foundation and Foundation.Collections projections. We do not import
        # those child namespaces directly because Pylance may flag them even
        # when the geolocation package is installed correctly.
        import importlib
        _winrt_geolocation = importlib.import_module(
            "winrt.windows.devices.geolocation"
        )
        WINRT_LOCATION_AVAILABLE = True
        WINRT_LOCATION_IMPORT_ERROR = ""
        print("Windows location support: OK")
        return True
    except Exception as second_error:
        WINRT_LOCATION_IMPORT_ERROR = str(second_error) or repr(second_error)
        print("WINRT LOCATION LOAD ERROR:", WINRT_LOCATION_IMPORT_ERROR)
        return False


_load_winrt_location_support()

WINRT_LOCATION_ACCESS_CHECKED = False
WINRT_LOCATION_ACCESS_ALLOWED = False

LOCATION_TRACKING = False
LOCATION_TRACKER_THREAD = None
LAST_LOCATION = None
LAST_LOCATION_DETAILS = None
LOCATION_LOCK = threading.Lock()


def _powershell_location_script():
    """Read the Windows desktop location provider through Windows PowerShell."""
    return r"""
$ErrorActionPreference = 'SilentlyContinue'
try {
    Add-Type -AssemblyName System.Device
    $watcher = New-Object System.Device.Location.GeoCoordinateWatcher
    # Do not assign DesiredAccuracy here: this legacy PowerShell projection
    # exposes it as read-only on some Windows/.NET builds.
    $started = $watcher.TryStart($false, [TimeSpan]::FromSeconds(15))
    if (-not $started) {
        $status = try { $watcher.Status.ToString() } catch { 'Unknown' }
        $permission = try { $watcher.Permission.ToString() } catch { 'Unknown' }
        @{ok=$false; error='NO_LOCATION_DATA'; status=$status; permission=$permission} | ConvertTo-Json -Compress
        exit
    }
    $coord = $watcher.Position.Location
    if ($null -eq $coord -or $coord.IsUnknown) {
        $status = try { $watcher.Status.ToString() } catch { 'Unknown' }
        $permission = try { $watcher.Permission.ToString() } catch { 'Unknown' }
        @{ok=$false; error='NO_LOCATION_DATA'; status=$status; permission=$permission} | ConvertTo-Json -Compress
        exit
    }
    @{
        ok=$true
        latitude=[double]$coord.Latitude
        longitude=[double]$coord.Longitude
        accuracy=[double]$coord.HorizontalAccuracy
        altitude=[double]$coord.Altitude
        speed=[double]$coord.Speed
        status=$watcher.Status.ToString()
        permission=$watcher.Permission.ToString()
    } | ConvertTo-Json -Compress
    $watcher.Stop()
} catch {
    @{ok=$false; error='LOCATION_PROVIDER_ERROR'; details=$_.Exception.Message} | ConvertTo-Json -Compress
}
"""


async def _winrt_location_async():
    """Get a Windows location fix using the modern Windows.Devices.Geolocation API."""
    global WINRT_LOCATION_ACCESS_CHECKED, WINRT_LOCATION_ACCESS_ALLOWED

    if not WINRT_LOCATION_AVAILABLE:
        return {"ok": False, "error": "WINRT_NOT_INSTALLED"}

    try:
        # Windows requires an explicit location-access request before using
        # GetGeopositionAsync. The first call is made by Sara's foreground
        # command handler; later live-tracking calls reuse the granted access.
        if not WINRT_LOCATION_ACCESS_CHECKED:
            access = await _winrt_geolocation.Geolocator.request_access_async()
            WINRT_LOCATION_ACCESS_CHECKED = True
            if access != _winrt_geolocation.GeolocationAccessStatus.ALLOWED:
                if access == _winrt_geolocation.GeolocationAccessStatus.DENIED:
                    return {"ok": False, "error": "LOCATION_PERMISSION_DENIED", "access": str(access)}
                return {"ok": False, "error": "LOCATION_PERMISSION_UNSPECIFIED", "access": str(access)}
            WINRT_LOCATION_ACCESS_ALLOWED = True

        if not WINRT_LOCATION_ACCESS_ALLOWED:
            return {"ok": False, "error": "LOCATION_PERMISSION_DENIED"}

        locator = _winrt_geolocation.Geolocator()
        # Leave the Windows default accuracy unchanged. Some PyWinRT builds
        # expose DesiredAccuracyInMeters differently, so setting it is not
        # required to obtain a normal location fix.
        position = await asyncio.wait_for(locator.get_geoposition_async(), timeout=20)
        coordinate = position.coordinate
        latitude = float(coordinate.latitude)
        longitude = float(coordinate.longitude)
        accuracy = float(coordinate.accuracy) if coordinate.accuracy is not None else -1.0

        return {
            "ok": True,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "provider": "Windows.Devices.Geolocation",
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": "LOCATION_TIMEOUT"}
    except Exception as error:
        details = str(error) or repr(error)
        print("WINRT LOCATION ERROR:", details)
        return {"ok": False, "error": "LOCATION_PROVIDER_ERROR", "details": details}


def _get_current_windows_location():
    """Get a current Windows location fix, preferring the modern WinRT API."""
    if os.name != "nt":
        return {"ok": False, "error": "WINDOWS_ONLY"}

    # Preferred path: Windows.Devices.Geolocation. This is the modern API
    # Microsoft documents for Windows desktop location access.
    if WINRT_LOCATION_AVAILABLE:
        try:
            result = asyncio.run(_winrt_location_async())
            return result
        except RuntimeError as error:
            # asyncio.run cannot be nested. This should not happen in Sara's
            # normal synchronous command loop, but keep the legacy fallback.
            print("WINRT EVENT LOOP ERROR:", repr(error))
        except Exception as error:
            print("WINRT LOCATION CALL ERROR:", repr(error))
    else:
        print("WINRT LOCATION IMPORT ERROR:", WINRT_LOCATION_IMPORT_ERROR)
        return {
            "ok": False,
            "error": "WINRT_NOT_INSTALLED",
            "details": WINRT_LOCATION_IMPORT_ERROR,
        }

    # Legacy fallback is used only if the modern provider was unavailable
    # before this call. If the modern provider itself reports an error, that
    # error is returned directly so Sara does not hide the real cause.
    try:
        completed = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command",
                _powershell_location_script(),
            ],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "POWERSHELL_MISSING"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "LOCATION_TIMEOUT"}
    except Exception as error:
        print("LOCATION PROCESS ERROR:", repr(error))
        return {"ok": False, "error": "LOCATION_PROCESS_ERROR", "details": repr(error)}

    raw = (completed.stdout or "").strip()
    if not raw:
        print("LOCATION POWERSHELL ERROR:", (completed.stderr or "").strip())
        return {"ok": False, "error": "NO_LOCATION_DATA"}

    for line in reversed([item.strip() for item in raw.splitlines() if item.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            if data.get("ok"):
                data["timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")
            return data

    print("LOCATION JSON ERROR:", raw[-1000:])
    return {"ok": False, "error": "LOCATION_DATA_INVALID"}


def _location_map_url(latitude, longitude):
    return f"https://www.google.com/maps?q={latitude:.7f},{longitude:.7f}"


def _reverse_geocode_location(latitude, longitude):
    """Resolve GPS coordinates to area, district, state, and country."""
    params = urllib.parse.urlencode({
        "lat": f"{latitude:.7f}",
        "lon": f"{longitude:.7f}",
        "format": "jsonv2",
        "addressdetails": "1",
        "zoom": "18",
        "accept-language": "en",
    })
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Sara-Voice-Assistant/2.0 (location lookup)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        address = data.get("address", {}) if isinstance(data, dict) else {}
        area = (
            address.get("neighbourhood")
            or address.get("suburb")
            or address.get("quarter")
            or address.get("village")
            or address.get("town")
            or address.get("city")
            or address.get("municipality")
            or ""
        )
        district = (
            address.get("state_district")
            or address.get("district")
            or address.get("county")
            or ""
        )
        state = address.get("state") or address.get("region") or ""
        country = address.get("country") or ""
        city = address.get("city") or address.get("town") or address.get("village") or ""
        return {
            "ok": True,
            "area": area,
            "district": district,
            "state": state,
            "country": country,
            "city": city,
            "display_name": data.get("display_name", ""),
        }
    except Exception as error:
        print("REVERSE GEOCODE ERROR:", repr(error))
        return {"ok": False, "error": "REVERSE_GEOCODE_ERROR"}


def _get_location_details(location):
    global LAST_LOCATION_DETAILS
    with LOCATION_LOCK:
        cached = dict(LAST_LOCATION_DETAILS) if isinstance(LAST_LOCATION_DETAILS, dict) else None
        cached_lat = LAST_LOCATION.get("latitude") if isinstance(LAST_LOCATION, dict) else None
        cached_lon = LAST_LOCATION.get("longitude") if isinstance(LAST_LOCATION, dict) else None
    if cached and cached_lat == location.get("latitude") and cached_lon == location.get("longitude"):
        return cached
    details = _reverse_geocode_location(location["latitude"], location["longitude"])
    if details.get("ok"):
        details["latitude"] = location["latitude"]
        details["longitude"] = location["longitude"]
        with LOCATION_LOCK:
            LAST_LOCATION_DETAILS = details
    return details


def _speak_location(location, prefix="Your current location is"):
    if not location.get("ok"):
        return False
    latitude = location["latitude"]
    longitude = location["longitude"]
    details = _get_location_details(location)
    if details.get("ok"):
        parts = []
        for label in ("area", "district", "state", "country"):
            value = details.get(label, "")
            if value and value not in parts:
                parts.append(value)
        if parts:
            speak(f"{prefix} {', '.join(parts)}.")
        else:
            speak(f"{prefix} latitude {latitude:.6f}, longitude {longitude:.6f}.")
    else:
        speak(f"{prefix} latitude {latitude:.6f}, longitude {longitude:.6f}. I could not resolve the place name right now.")
    print("Coordinates:", latitude, longitude)
    print("Map:", _location_map_url(latitude, longitude))
    return True


def _location_error_message(location):
    error = location.get("error")
    if error == "WINDOWS_ONLY":
        speak("GPS location is available when Sara is running on Windows.")
    elif error == "POWERSHELL_MISSING":
        speak("I could not find Windows PowerShell on this computer.")
    elif error == "WINRT_NOT_INSTALLED":
        speak("Sara could not load the Windows location API. I tried to install the required WinRT packages automatically. Please check the terminal for the installation error, then restart Sara.")
    elif error == "LOCATION_PERMISSION_DENIED":
        speak("Windows is denying Sara location access. Location Services may be on, but desktop-app location access is still being denied. Please check Windows Location privacy settings and restart Sara.")
    elif error == "LOCATION_PERMISSION_UNSPECIFIED":
        speak("Windows did not grant Sara a location permission state. Please restart Sara after confirming Location Services and desktop-app location access are on.")
    elif error in {"NO_LOCATION_DATA", "LOCATION_TIMEOUT", "LOCATION_PROVIDER_ERROR"}:
        speak("Windows did not return a location fix. Your location settings can be on and this can still happen when Windows has no usable location source. Make sure Wi-Fi is connected and, if your laptop has a GNSS GPS sensor, that Windows recognizes it.")
        if location.get("status") or location.get("permission"):
            print("Location status:", location.get("status", "unknown"), "Permission:", location.get("permission", "unknown"))
        if location.get("details"):
            print("Provider details:", location.get("details"))
    elif error == "REVERSE_GEOCODE_ERROR":
        speak("I got your GPS coordinates, but I could not resolve the area and district names right now.")
    else:
        speak("I could not get your location from Windows. Please check Windows Location Services and try again.")
    # A location failure has already been handled and spoken to the user.
    # Return True so the main router does not fall through to the generic
    # "I am still learning that command" response.
    return True


def _location_tracker_worker():
    global LOCATION_TRACKING, LAST_LOCATION
    while LOCATION_TRACKING:
        location = _get_current_windows_location()
        if location.get("ok"):
            with LOCATION_LOCK:
                LAST_LOCATION = location
            accuracy = location.get("accuracy")
            suffix = f" | accuracy {accuracy:.0f} m" if isinstance(accuracy, (int, float)) and accuracy >= 0 else ""
            print(f"LIVE LOCATION: {location['latitude']:.6f}, {location['longitude']:.6f}{suffix}")
        else:
            print("LIVE LOCATION ERROR:", location.get("error"))
        for _ in range(50):
            if not LOCATION_TRACKING:
                break
            time.sleep(0.1)


def _start_live_location():
    global LOCATION_TRACKING, LOCATION_TRACKER_THREAD, LAST_LOCATION
    if LOCATION_TRACKING:
        speak("Live location tracking is already running.")
        return True
    first = _get_current_windows_location()
    if not first.get("ok"):
        return _location_error_message(first)
    with LOCATION_LOCK:
        LAST_LOCATION = first
    LOCATION_TRACKING = True
    LOCATION_TRACKER_THREAD = threading.Thread(target=_location_tracker_worker, daemon=True)
    LOCATION_TRACKER_THREAD.start()
    speak("Live location tracking has started. Sara will keep updating the device location while the assistant is running.")
    _speak_location(first, prefix="Your live location starts at")
    return True


def _stop_live_location():
    global LOCATION_TRACKING, LOCATION_TRACKER_THREAD
    if not LOCATION_TRACKING:
        speak("Live location tracking is not running.")
        return True
    LOCATION_TRACKING = False
    thread = LOCATION_TRACKER_THREAD
    LOCATION_TRACKER_THREAD = None
    if thread and thread.is_alive():
        thread.join(timeout=2)
    speak("Live location tracking has been stopped.")
    return True


def _get_best_location():
    with LOCATION_LOCK:
        cached = dict(LAST_LOCATION) if isinstance(LAST_LOCATION, dict) else None
    if cached and cached.get("ok"):
        return cached
    return _get_current_windows_location()


def _extract_phone_number(command):
    match = re.search(r"(?:\+\d{8,15}|\d{10,15})", command)
    if not match:
        return ""
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _extract_whatsapp_contact_name(command):
    """Extract a spoken WhatsApp contact name after 'with/to/contact'."""
    patterns = (
        r"\b(?:with|to)\s+(?:my\s+)?contact\s+(.+)$",
        r"\b(?:with|to)\s+(.+?)\s+(?:on|in)\s+whatsapp$",
        r"\b(?:with|to)\s+(.+?)\s+whatsapp$",
    )
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            name = match.group(1).strip(" .,!?")
            if name and not re.fullmatch(r"(?:my\s+)?location", name):
                return name
    return ""


def _open_whatsapp_location(command, live=False):
    location = _get_best_location()
    if not location.get("ok"):
        return _location_error_message(location)
    latitude = location["latitude"]
    longitude = location["longitude"]
    map_url = _location_map_url(latitude, longitude)
    contact_name = _extract_whatsapp_contact_name(command)
    details = _get_location_details(location)
    place = ", ".join(
        value for value in (
            details.get("area", ""), details.get("district", ""),
            details.get("state", ""), details.get("country", "")
        ) if value
    ) if details.get("ok") else ""
    message = f"My current location: {map_url}"
    if place:
        message += f"\nLocation: {place}"
    if live:
        message += "\n\nThis is a map link. Native WhatsApp Live Location must be started and confirmed inside WhatsApp."

    phone = _extract_phone_number(command)
    encoded = urllib.parse.quote(message, safe="")
    if phone:
        webbrowser.open(f"https://wa.me/{phone}?text={encoded}")
        speak(f"I opened WhatsApp for {contact_name or 'the contact'} with your location message prepared. Please press Send.")
    else:
        webbrowser.open("https://web.whatsapp.com/")
        if contact_name:
            speak(f"I opened WhatsApp and prepared your location. Search for {contact_name}, open that chat, and send the prepared location message. WhatsApp does not provide a public Windows link that can select a contact by name automatically.")
        else:
            speak("I opened WhatsApp with your current location ready to share. Choose the contact and press Send.")
    print("WhatsApp contact:", contact_name or "not specified")
    print("Location message:", message)
    return True


def handle_command13(command):
    text = normalize_command(command)
    text = strip_assistant_address(text)
    if not text:
        return False

    if text in {
        "stop live location", "stop live location tracking", "stop tracking",
        "stop location tracking", "end live location", "turn off live location",
        "disable live location", "cancel live location", "cancel location tracking"
    }:
        return _stop_live_location()

    if "whatsapp" in text and any(term in text for term in ("share", "send", "location", "track")):
        live = "live location" in text or "track my location" in text or "live tracking" in text
        return _open_whatsapp_location(text, live=live)

    if text in {
        "start live location", "start live location tracking", "track my location",
        "start tracking my location", "start location tracking", "track my live location",
        "show my live location", "show live location", "start live gps tracking",
        "track my live gps location", "start gps tracking", "start gps live tracking"
    }:
        return _start_live_location()

    current_location_phrases = {
        "where am i", "where am i now", "what is my current location",
        "what's my current location", "get my current location", "get my location",
        "show my current location", "show my location", "find my location", "locate me",
        "what is my gps location", "what's my gps location", "get my gps location",
        "show my gps location", "give me my coordinates", "what are my coordinates",
        "get my coordinates", "latitude and longitude", "give me latitude and longitude",
        "my latitude and longitude", "where can i", "where can i now", "tell me where i am now", "say my present location", "tell me my present location",
        "what is my present location", "where am i currently", "tell me where i am"
    }
    if text in current_location_phrases:
        location = _get_current_windows_location()
        if location.get("ok"):
            _speak_location(location)
            return True
        return _location_error_message(location)

    if text in {
        "show my location on the map", "show my location in google maps",
        "open my location on the map", "open my present location on the map"
    }:
        location = _get_best_location()
        if not location.get("ok"):
            return _location_error_message(location)
        webbrowser.open(_location_map_url(location["latitude"], location["longitude"]))
        speak("I opened your current location on the map.")
        return True

    gps_question = any(term in text for term in (
        "what is gps", "what does gps mean", "how does gps work", "how gps works",
        "gps full form", "what is global positioning system", "explain gps"
    ))
    if gps_question:
        speak("GPS means Global Positioning System. It uses satellite signals and location technology to estimate a device's position, commonly expressed as latitude and longitude.")
        return True

    if text in {"is location on", "is gps on", "is my location on", "location status", "gps status", "check my location service"}:
        location = _get_current_windows_location()
        if location.get("ok"):
            speak("Windows is providing a location fix to Sara right now.")
        else:
            _location_error_message(location)
        return True

    return False


# ---------------------- Command 14: Applications, Browser, Settings, System Data, Battery, Brightness & Volume ----------------------
# Command 14 is isolated here. Commands 1-13 above are intentionally preserved.
# Windows-specific controls use documented Windows APIs/URIs where possible.

import ctypes
import subprocess
import webbrowser

SETTINGS_OPENED = False
LAST_OPENED_APPLICATION = ""

# ---------------------- Application catalog ----------------------
# Keys are deliberately exact after normalize_command(). ASR variants are included
# only when they are strongly associated with the intended application.
START_MENU_APP_ALIASES = {
    "amazon": ("Amazon", "Amazon Shopping"),
    "aha": ("Aha",),
    "zee5": ("ZEE5", "Zee5"),
    "netflix": ("Netflix",),
    "sonylive": ("Sony LIV", "SonyLIV", "Sony Live"),
    "prime video": ("Prime Video", "Amazon Prime Video"),
    "jio hotstar": ("JioHotstar", "Jio Hotstar", "Hotstar"),
    "spotify": ("Spotify",),
    "youtube": ("YouTube",),
    "chatgpt": ("ChatGPT",),
    "copilot": ("Microsoft Copilot", "Copilot"),
    "gemini ai": ("Gemini", "Google Gemini"),
    "claude": ("Claude",),
    "snapchat": ("Snapchat",),
    "whatsapp": ("WhatsApp",),
    "instagram": ("Instagram",),
    "facebook": ("Facebook",),
    "twitter": ("Twitter", "X"),
    "microsoft store": ("Microsoft Store",),
    "microsoft edge": ("Microsoft Edge",),
    "chrome": ("Google Chrome", "Chrome"),
    "lenovo vantage": ("Lenovo Vantage",),
    "dolby access": ("Dolby Access",),
    "camera": ("Camera",),
    "visual studio code": ("Visual Studio Code", "Visual Studio Code - Insiders"),
    "asphalt 8 airborne": ("Asphalt 8: Airborne", "Asphalt 8 Airborne"),
    "adobe express": ("Adobe Express",),
    "phone link": ("Phone Link",),
    "microsoft photos": ("Microsoft Photos", "Photos"),
    "speechify": ("Speechify",),
    "intel graphics software": ("Intel Graphics Software", "Intel Graphics Command Center"),
    "armoury crate": ("Armoury Crate",),
    "hp command center": ("HP Command Center",),
    "my hp": ("myHP", "My HP"),
    "hp support assistant": ("HP Support Assistant",),
    "dell optimizer": ("Dell Optimizer",),
    "msi center": ("MSI Center",),
    "acer care center": ("Acer Care Center",),
    "github": ("GitHub", "GitHub Desktop"),
    "linkedin": ("LinkedIn",),
    "calculator": ("Calculator",),
    "notepad": ("Notepad",),
    "paint": ("Paint", "Microsoft Paint"),
    "word": ("Word", "Microsoft Word"),
    "excel": ("Excel", "Microsoft Excel"),
    "powerpoint": ("PowerPoint", "Microsoft PowerPoint"),
    "task manager": ("Task Manager",),
    "clock": ("Clock", "Windows Clock"),
    "snipping tool": ("Snipping Tool",),
    "terminal": ("Windows Terminal", "Terminal"),
    "command prompt": ("Command Prompt",),
}

WEB_APPLICATION_URLS = {
    "amazon": "https://www.amazon.in/",
    "aha": "https://www.aha.video/",
    "zee5": "https://www.zee5.com/",
    "netflix": "https://www.netflix.com/",
    "sonylive": "https://www.sonyliv.com/",
    "prime video": "https://www.primevideo.com/",
    "jio hotstar": "https://www.hotstar.com/",
    "spotify": "https://open.spotify.com/",
    "youtube": "https://www.youtube.com/",
    "chatgpt": "https://chatgpt.com/",
    "copilot": "https://copilot.microsoft.com/",
    "gemini ai": "https://gemini.google.com/",
    "claude": "https://claude.ai/",
    "snapchat": "https://web.snapchat.com/",
    "whatsapp": "https://web.whatsapp.com/",
    "instagram": "https://www.instagram.com/",
    "facebook": "https://www.facebook.com/",
    "twitter": "https://x.com/",
    "github": "https://github.com/",
    "linkedin": "https://www.linkedin.com/",
    "adobe express": "https://new.express.adobe.com/",
    "speechify": "https://speechify.com/",
    "google": "https://www.google.com/",
}

APP_ALIASES = {
    "amazon": "amazon", "amazon shopping": "amazon",
    "aha": "aha",
    "zee5": "zee5", "zee 5": "zee5",
    "netflix": "netflix",
    "sony live": "sonylive", "sony liv": "sonylive", "sonylive": "sonylive", "sony liv app": "sonylive", "sony live app": "sonylive",
    "prime video": "prime video", "amazon prime video": "prime video", "prime": "prime video",
    "jio hotstar": "jio hotstar", "jiohotstar": "jio hotstar", "hotstar": "jio hotstar",
    "spotify": "spotify", "youtube": "youtube",
    "chatgpt": "chatgpt", "chat gpt": "chatgpt",
    "copilot": "copilot", "microsoft copilot": "copilot",
    "gemini": "gemini ai", "gemini ai": "gemini ai", "google gemini": "gemini ai",
    "claude": "claude", "claude ai": "claude", "claud": "claude", "claud ai": "claude", "cloud ai": "claude", "cloud a i": "claude", "cloud": "claude",
    "snapchat": "snapchat", "whatsapp": "whatsapp", "whatsapp web": "whatsapp",
    "instagram": "instagram", "facebook": "facebook", "twitter": "twitter", "x": "twitter",
    "file explorer": "file explorer", "explorer": "file explorer", "files": "file explorer",
    "microsoft store": "microsoft store", "microstore": "microsoft store", "micro store": "microsoft store", "store": "microsoft store",
    "microsoft edge": "microsoft edge", "edge": "microsoft edge",
    "chrome": "chrome", "google chrome": "chrome",
    "google": "google", "browser": "browser", "web browser": "browser",
    "lenovo vantage": "lenovo vantage",
    "dolby access": "dolby access", "dolby asus": "dolby access", "dolby sss": "dolby access", "dolby axs": "dolby access",
    "camera": "camera",
    "visual studio code": "visual studio code", "vs code": "visual studio code", "vscode": "visual studio code",
    "asphalt 8": "asphalt 8 airborne", "asphalt 8 airborne": "asphalt 8 airborne", "asphalt 8 airborne game": "asphalt 8 airborne",
    "adobe express": "adobe express", "phone link": "phone link",
    "microsoft photos": "microsoft photos", "photos": "microsoft photos",
    "speechify": "speechify", "speech if i": "speechify", "speech ify": "speechify", "speechify app": "speechify", "speechify application": "speechify",
    "intel graphics software": "intel graphics software", "intel graphics": "intel graphics software", "intel graphics command center": "intel graphics software",
    "armoury crate": "armoury crate", "asus armoury crate": "armoury crate",
    "hp command center": "hp command center", "hp command centre": "hp command center",
    "my hp": "my hp", "myhp": "my hp",
    "hp support assistant": "hp support assistant", "dell optimizer": "dell optimizer",
    "msi center": "msi center", "acer care center": "acer care center",
    "github": "github", "linkedin": "linkedin",
    "calculator": "calculator", "calc": "calculator", "notepad": "notepad",
    "paint": "paint", "microsoft paint": "paint", "word": "word", "microsoft word": "word",
    "excel": "excel", "microsoft excel": "excel", "powerpoint": "powerpoint", "power point": "powerpoint",
    "microsoft powerpoint": "powerpoint", "task manager": "task manager", "clock": "clock",
    "windows clock": "clock", "snipping tool": "snipping tool", "terminal": "terminal",
    "windows terminal": "terminal", "command prompt": "command prompt", "cmd": "command prompt",
    "dolby": "dolby access",
}

PROCESS_NAMES = {
    "amazon": ("Amazon.exe",), "aha": ("Aha.exe",), "zee5": ("ZEE5.exe",),
    "netflix": ("Netflix.exe",), "sonylive": ("SonyLIV.exe", "SonyLiv.exe"),
    "prime video": ("PrimeVideo.exe",), "jio hotstar": ("JioHotstar.exe", "Hotstar.exe"),
    "spotify": ("Spotify.exe",), "youtube": ("YouTube.exe",), "chatgpt": ("ChatGPT.exe",),
    "copilot": ("Copilot.exe",), "gemini ai": ("Gemini.exe",), "claude": ("Claude.exe",),
    "snapchat": ("Snapchat.exe",), "whatsapp": ("WhatsApp.exe", "WhatsApp.Root.exe"),
    "instagram": ("Instagram.exe",), "facebook": ("Facebook.exe",), "twitter": ("Twitter.exe",),
    "microsoft store": ("WinStore.App.exe",), "microsoft edge": ("msedge.exe",), "chrome": ("chrome.exe",),
    "lenovo vantage": ("LenovoVantage.exe", "Lenovo.Modern.ImController.PluginHost.exe"),
    "dolby access": ("DolbyAccess.exe",), "camera": ("WindowsCamera.exe", "Microsoft.WindowsCamera.exe"),
    "visual studio code": ("Code.exe",), "asphalt 8 airborne": ("Asphalt8.exe", "Asphalt8Airborne.exe"),
    "adobe express": ("Adobe Express.exe",), "phone link": ("PhoneExperienceHost.exe",),
    "microsoft photos": ("Microsoft.Photos.exe", "PhotosApp.exe"), "speechify": ("Speechify.exe",),
    "intel graphics software": ("IntelGraphicsSoftware.exe", "IGCC.exe"), "armoury crate": ("ArmouryCrate.exe",),
    "hp command center": ("HPCommandCenter.exe",), "my hp": ("myHP.exe", "MyHP.exe"),
    "hp support assistant": ("HPSupportAssistant.exe",), "dell optimizer": ("DellOptimizer.exe",),
    "msi center": ("MSI.CentralServer.exe", "MSI Center.exe"), "acer care center": ("AcerCareCenter.exe",),
    "github": ("GitHubDesktop.exe",), "linkedin": ("LinkedIn.exe",), "calculator": ("CalculatorApp.exe", "Calculator.exe"),
    "notepad": ("notepad.exe",), "file explorer": (),
}


def _command14_powershell(script, timeout=15):
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            print("POWERSHELL ERROR:", completed.stderr.strip())
            return ""
        return completed.stdout.strip()
    except Exception as error:
        print("POWERSHELL RUN ERROR:", repr(error))
        return ""


def _command14_find_start_app(app_names):
    names_literal = ",".join("'" + str(x).replace("'", "''") + "'" for x in app_names)
    script = f"$names=@({names_literal}); $apps=Get-StartApps; foreach($n in $names){{ $a=$apps | Where-Object {{ $_.Name -eq $n }} | Select-Object -First 1; if($a){{ Write-Output ($a.Name+'|'+$a.AppID); exit }} }}"
    result = _command14_powershell(script, timeout=10)
    if "|" in result:
        name, appid = result.split("|",1)
        return name.strip(), appid.strip()
    return None


def _command14_launch_start_app(app_key):
    names = START_MENU_APP_ALIASES.get(app_key, ())
    found = _command14_find_start_app(names)
    if not found:
        return False
    _, appid = found
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return True
    except Exception as error:
        print("START APP LAUNCH ERROR:", repr(error))
        return False


def _command14_open_app(app_key):
    global LAST_OPENED_APPLICATION
    try:
        if app_key == "notepad":
            subprocess.Popen(["notepad.exe"])
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Notepad.")
            return True
        if app_key == "calculator":
            subprocess.Popen(["calc.exe"])
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Calculator.")
            return True
        direct_apps = {"paint": ["mspaint.exe"], "task manager": ["taskmgr.exe"], "command prompt": ["cmd.exe"], "terminal": ["wt.exe"], "snipping tool": ["snippingtool.exe"], "word": ["winword.exe"], "excel": ["excel.exe"], "powerpoint": ["powerpnt.exe"]}
        if app_key in direct_apps:
            try:
                subprocess.Popen(direct_apps[app_key], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                LAST_OPENED_APPLICATION = app_key
                speak(f"Opening {app_key}.")
                return True
            except Exception as launch_error:
                print("DIRECT APP LAUNCH ERROR:", repr(launch_error))
                # Continue to Start-menu lookup and web fallback where appropriate.
        if app_key == "file explorer":
            subprocess.Popen(["explorer.exe"])
            LAST_OPENED_APPLICATION = app_key
            speak("I opened File Explorer.")
            return True
        if app_key == "microsoft store":
            os.startfile("ms-windows-store:")
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Microsoft Store.")
            return True
        if app_key == "microsoft edge":
            subprocess.Popen(["msedge.exe"], creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Microsoft Edge.")
            return True
        if app_key == "chrome":
            subprocess.Popen(["chrome.exe"], creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Chrome.")
            return True
        if app_key == "google":
            webbrowser.open("https://www.google.com/")
            LAST_OPENED_APPLICATION = app_key
            speak("I opened Google.")
            return True
        if app_key == "browser":
            webbrowser.open("https://www.google.com/")
            LAST_OPENED_APPLICATION = app_key
            speak("I opened the browser.")
            return True

        if _command14_launch_start_app(app_key):
            LAST_OPENED_APPLICATION = app_key
            speak(f"I opened {app_key}.")
            return True

        url = WEB_APPLICATION_URLS.get(app_key)
        if url:
            webbrowser.open(url)
            LAST_OPENED_APPLICATION = app_key
            speak(f"I opened {app_key} in the browser.")
            return True

        speak(f"I couldn't find {app_key} on this computer.")
        return True
    except Exception as error:
        print("OPEN APP ERROR:", repr(error))
        url = WEB_APPLICATION_URLS.get(app_key)
        if url:
            try:
                webbrowser.open(url)
                LAST_OPENED_APPLICATION = app_key
                speak(f"I opened {app_key} in the browser.")
                return True
            except Exception:
                pass
        speak(f"I couldn't open {app_key}.")
        return True


def _command14_close_app(app_key):
    global LAST_OPENED_APPLICATION
    if app_key == "file explorer":
        # Never kill explorer.exe: it owns the Windows shell. Close the active window instead.
        if _command14_send_alt_f4():
            speak("I closed the current File Explorer window.")
        else:
            speak("I couldn't close the File Explorer window.")
        return True
    if app_key == "microsoft store":
        names=("WinStore.App.exe",)
    elif app_key == "microsoft edge":
        names=("msedge.exe",)
    elif app_key == "chrome":
        names=("chrome.exe",)
    else:
        names=PROCESS_NAMES.get(app_key, ())
    if not names:
        if app_key == LAST_OPENED_APPLICATION and _command14_send_alt_f4():
            speak(f"I closed {app_key}.")
        else:
            speak(f"I don't have a safe close action for {app_key}.")
        return True
    closed=False
    for process_name in names:
        try:
            r=subprocess.run(["taskkill","/IM",process_name,"/T","/F"],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if r.returncode==0:
                closed=True
        except Exception as error:
            print("CLOSE APP ERROR:",repr(error))
    if closed:
        if LAST_OPENED_APPLICATION==app_key: LAST_OPENED_APPLICATION=""
        speak(f"I closed {app_key}.")
    else:
        speak(f"{app_key} is not running as a desktop process, so I could not close it.")
    return True


# ---------------------- Settings ----------------------
# These are documented ms-settings identifiers. Availability can vary by Windows edition/version.
SETTINGS_SECTION_URIS = {
    "home": "",
    "sound": "sound", "location": "privacy-location", "pictures": "privacy-pictures", "bluetooth": "bluetooth",
    "display": "display", "notifications": "notifications", "focus": "quiethours", "storage": "storagesense",
    "share": "crossdevice", "multitasking": "multitasking", "ai components": "systemcomponents",
    "system components": "systemcomponents", "clipboard": "clipboard", "remote desktop": "remotedesktop",
    "recovery": "recovery", "windows update": "windowsupdate", "microsoft 365": "workplace", "onedrive": "onedrive",
    "usb": "usb", "autoplay": "autoplay", "pen and windows ink": "pen", "touchpad": "devices-touchpad",
    "keyboard": "keyboard", "mouse": "mousetouchpad", "mobile devices": "mobile-devices", "cameras": "camera",
    "wifi": "network-wifi", "wi fi": "network-wifi", "vpn": "network-vpn", "mobile hotspot": "network-mobilehotspot",
    "airplane mode": "network-airplanemode", "proxy": "network-proxy", "dial up": "network-dialup",
    "advanced network settings": "network-advancedsettings", "background": "personalization-background", "colors": "colors",
    "themes": "themes", "dynamic lighting": "personalization-dynamiclighting", "lockscreen": "lockscreen",
    "lock screen": "lockscreen", "text input": "typing", "fonts": "fonts", "taskbar": "taskbar",
    "installed apps": "appsfeatures", "advanced apps settings": "apps-advanced", "default apps": "defaultapps",
    "offline maps": "maps", "apps for websites": "appsforwebsites", "system": "system", "devices": "bluetooth",
    "network and internet": "network-status", "personalization": "personalization", "apps": "appsfeatures",
    "accounts": "accounts", "account": "accounts", "time and language": "dateandtime", "gaming": "gaming",
    "accessibility": "easeofaccess", "privacy and security": "privacy", "privacy": "privacy",
    "battery": "powersleep", "power": "powersleep", "battery and power": "powersleep",
}


def _command14_open_settings(section=""):
    global SETTINGS_OPENED
    uri="ms-settings:"+(section or "")
    try:
        os.startfile(uri)
        SETTINGS_OPENED=True
        return True
    except Exception as error:
        print("SETTINGS OPEN ERROR:",repr(error))
        try:
            subprocess.Popen(["explorer.exe", uri], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            SETTINGS_OPENED=True
            return True
        except Exception as fallback_error:
            print("SETTINGS FALLBACK ERROR:", repr(fallback_error))
            return False


def _command14_send_alt_left():
    try:
        u=ctypes.windll.user32; u.keybd_event(0x12,0,0,0); u.keybd_event(0x25,0,0,0); u.keybd_event(0x25,0,2,0); u.keybd_event(0x12,0,2,0); return True
    except Exception as error: print("BACK KEY ERROR:",repr(error)); return False


def _command14_send_alt_f4():
    try:
        u=ctypes.windll.user32; u.keybd_event(0x12,0,0,0); u.keybd_event(0x73,0,0,0); u.keybd_event(0x73,0,2,0); u.keybd_event(0x12,0,2,0); return True
    except Exception as error: print("CLOSE KEY ERROR:",repr(error)); return False


def _command14_close_settings():
    global SETTINGS_OPENED
    closed=False
    try:
        r=subprocess.run(["taskkill","/IM","SystemSettings.exe","/T","/F"],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        closed=(r.returncode==0)
    except Exception as error: print("SETTINGS CLOSE ERROR:",repr(error))
    if not closed: closed=_command14_send_alt_f4()
    SETTINGS_OPENED=False
    if closed: speak("I closed Windows Settings.")
    else: speak("I couldn't close Windows Settings.")
    return True


def _command14_open_windows_search():
    try:
        u=ctypes.windll.user32; u.keybd_event(0x5B,0,0,0); u.keybd_event(0x53,0,0,0); u.keybd_event(0x53,0,2,0); u.keybd_event(0x5B,0,2,0); return True
    except Exception as error: print("SEARCH KEY ERROR:",repr(error)); return False


def _command14_open_start_menu():
    try:
        u=ctypes.windll.user32; u.keybd_event(0x5B,0,0,0); u.keybd_event(0x5B,0,2,0); return True
    except Exception as error: print("START KEY ERROR:",repr(error)); return False


def _command14_search_browser(query):
    url="https://www.google.com/search?"+urllib.parse.urlencode({"q":query}) if query else "https://www.google.com/"
    webbrowser.open(url); speak(f"I searched Google for {query}." if query else "I opened Google."); return True


def _command14_extract_search_query(text):
    for p in (r"^search (.+?) on google$",r"^search google for (.+)$",r"^browser search (?:for )?(.+)$",r"^search(?: for)? (.+)$",r"^google (?:search for )?(.+)$",r"^look up (.+)$",r"^browse for (.+)$"):
        m=re.match(p,text)
        if m:return m.group(1).strip()
    return ""


def _command14_extract_laptop_search(text):
    for p in (r"^search (?:the )?(?:laptop|computer|pc) for (.+)$",r"^search (?:my )?(?:laptop|computer|pc) for (.+)$",r"^search applications for (.+)$",r"^search apps for (.+)$",r"^find application (.+)$",r"^find app (.+)$",r"^find (.+) in windows search$"):
        m=re.match(p,text)
        if m:return m.group(1).strip()
    return ""


def _command14_search_laptop(query):
    if not _command14_open_windows_search(): return True
    if query:
        time.sleep(.3)
        try:
            ps="Set-Clipboard -Value " + json.dumps(query)
            _command14_powershell(ps,timeout=5)
            u=ctypes.windll.user32; u.keybd_event(0x11,0,0,0); u.keybd_event(0x56,0,0,0); u.keybd_event(0x56,0,2,0); u.keybd_event(0x11,0,2,0)
        except Exception as error: print("WINDOWS SEARCH TYPE ERROR:",repr(error))
        speak(f"I opened Windows Search for {query}.")
    else: speak("I opened Windows Search.")
    return True


# ---------------------- Battery ----------------------
def _command14_get_battery():
    script=r'''$b=@(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue); if($b.Count -eq 0){'NO_BATTERY';exit}; $charge=($b|Measure-Object EstimatedChargeRemaining -Average).Average; $status=($b|Measure-Object BatteryStatus -Maximum).Maximum; $runtime=($b|Measure-Object EstimatedRunTime -Minimum).Minimum; "$([int][math]::Round($charge))|$([int]$status)|$([int]$runtime)"'''
    r=_command14_powershell(script,10)
    if not r or r=="NO_BATTERY": return None
    p=r.split("|")
    if len(p)!=3:return None
    try:return {"percent":max(0,min(100,int(p[0]))),"status":int(p[1]),"minutes":int(p[2])}
    except ValueError:return None


def _command14_battery_status_text(status):
    return {1:"discharging",2:"plugged in and charging",3:"fully charged",4:"low battery",5:"critical battery",6:"charging",7:"charging",8:"charging with low battery",9:"charging with critical battery",11:"partially charged"}.get(status,"status unknown")


def _command14_battery_answer(text):
    b=_command14_get_battery()
    if not b:
        speak("I couldn't read battery information from Windows."); return True
    t=text
    if "percentage" in t or "percent" in t or "how much battery" in t:
        speak(f"Your battery is at {b['percent']} percent."); return True
    if "charging" in t or "plugged" in t or "power status" in t:
        speak(f"Your laptop is {('plugged in and '+_command14_battery_status_text(b['status'])) if b['status'] in (2,6,7,8,9) else _command14_battery_status_text(b['status'])}."); return True
    if "remaining time" in t or "how much time" in t:
        m=b['minutes']
        if m<=0 or m>=71582788:speak("Windows did not provide an estimated remaining time.")
        else:
            h,mi=divmod(m,60); speak(f"You have about {h} hour{'s' if h!=1 else ''} {mi} minutes remaining." if h else f"You have about {mi} minutes remaining.")
        return True
    speak(f"Your battery is at {b['percent']} percent and is {_command14_battery_status_text(b['status'])}.")
    return True


# ---------------------- Brightness ----------------------
def _command14_brightness_value():
    r=_command14_powershell("$b=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty CurrentBrightness; if($null -ne $b){[int]$b}",8)
    try:return int(r) if r else None
    except ValueError:return None


def _command14_set_brightness(value):
    value=max(0,min(100,int(value)))
    script=f"$m=@(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue); if($m.Count -eq 0){{exit 2}}; foreach($x in $m){{Invoke-CimMethod -InputObject $x -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={value}}} -ErrorAction Stop | Out-Null}}"
    r=_command14_powershell(script,8)
    time.sleep(.25)
    actual=_command14_brightness_value()
    return actual is not None and abs(actual-value)<=2, actual


def _command14_extract_percent(text):
    m=re.search(r"\b(\d{1,3})\s*(?:%|percent|percentage)\b",text)
    if m:return max(0,min(100,int(m.group(1))))
    m=re.search(r"\bby\s+(\d{1,3})\b",text)
    return max(0,min(100,int(m.group(1)))) if m else None


def _command14_show_level(label,value):
    # Show only the value actually read back from Windows; never fabricate a percentage.
    try:
        import tkinter as tk
        root=tk.Tk(); root.title(f"Sara - {label}"); root.attributes("-topmost",True); root.resizable(False,False)
        tk.Label(root,text=f"{label}: {int(value)}%",font=("Segoe UI",22,"bold")).pack(padx=28,pady=(18,8))
        bar=tk.Canvas(root,width=260,height=20,highlightthickness=0); bar.pack(padx=28,pady=(0,18)); bar.create_rectangle(0,0,260,20,outline="gray"); bar.create_rectangle(0,0,2.6*int(value),20,fill="white",outline="white")
        root.after(1300,root.destroy); root.mainloop()
    except Exception as error: print("LEVEL DISPLAY ERROR:",repr(error))


def _command14_brightness(text):
    relevant=("brightness" in text or "screen brightness" in text or "display brightness" in text)
    if not relevant:return False
    current=_command14_brightness_value()
    if current is None:
        speak("Windows did not provide a controllable display brightness level on this laptop."); return True
    if any(x in text for x in ("show", "what is", "check", "tell me")) and not any(x in text for x in ("increase","decrease","set","raise","lower")):
        speak(f"Your brightness is {current} percent."); _command14_show_level("Brightness",current); return True
    value=_command14_extract_percent(text)
    if re.search(r"\b(?:increase|raise)\b",text):
        value=current+(value if value is not None else 10)
    elif re.search(r"\b(?:decrease|lower)\b",text):
        value=current-(value if value is not None else 10)
    elif re.search(r"\bset\b",text) and value is None:
        speak("Please tell me the brightness percentage."); return True
    elif value is None:
        speak(f"Your brightness is {current} percent."); _command14_show_level("Brightness",current); return True
    ok,actual=_command14_set_brightness(value)
    if not ok:
        speak("Windows could not change the real display brightness on this laptop. I did not show a fake percentage."); return True
    speak(f"Brightness is now {actual} percent."); _command14_show_level("Brightness",actual); return True


# ---------------------- Master volume via Windows Core Audio ----------------------
class _GUID(ctypes.Structure):
    _fields_=[("Data1",ctypes.c_ulong),("Data2",ctypes.c_ushort),("Data3",ctypes.c_ushort),("Data4",ctypes.c_ubyte*8)]


def _guid(s):
    import uuid
    u=uuid.UUID(s); b=u.bytes_le
    g=_GUID(); g.Data1=int.from_bytes(b[0:4],"little"); g.Data2=int.from_bytes(b[4:6],"little"); g.Data3=int.from_bytes(b[6:8],"little"); g.Data4=(ctypes.c_ubyte*8).from_buffer_copy(b[8:16]); return g


def _com_method(ptr,index,restype,argtypes,*args):
    vtbl=ctypes.cast(ptr,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn=ctypes.WINFUNCTYPE(restype,ctypes.c_void_p,*argtypes)(vtbl[index])
    return fn(ptr,*args)


def _release_com(ptr):
    if ptr:
        try:_com_method(ptr,2,ctypes.c_ulong,[]) 
        except Exception:pass


def _command14_audio_volume(action="get",value=None):
    ole32=ctypes.windll.ole32
    S_OK=0
    hr=ole32.CoInitializeEx(None,2)
    initialized=hr in (0,1)
    if not initialized and hr not in (0x80010106,): return None
    enumerator=ctypes.c_void_p(); device=ctypes.c_void_p(); endpoint=ctypes.c_void_p()
    try:
        clsid=_guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
        iid_enum=_guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
        iid_endpoint=_guid("5CDF2C82-841E-4546-9722-0CF74078229A")
        ole32.CoCreateInstance.argtypes=[ctypes.POINTER(_GUID),ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(_GUID),ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype=ctypes.c_long
        hr=ole32.CoCreateInstance(ctypes.byref(clsid),None,1,ctypes.byref(iid_enum),ctypes.byref(enumerator))
        if hr!=S_OK:return None
        hr=_com_method(enumerator,4,ctypes.c_long,[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)],0,0,ctypes.byref(device))
        if hr!=S_OK:return None
        hr=_com_method(device,3,ctypes.c_long,[ctypes.POINTER(_GUID),ctypes.c_uint32,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)],ctypes.byref(iid_endpoint),23,None,ctypes.byref(endpoint))
        if hr!=S_OK:return None
        scalar=ctypes.c_float()
        mute=ctypes.c_int()
        if action=="get":
            hr=_com_method(endpoint,9,ctypes.c_long,[ctypes.POINTER(ctypes.c_float)],ctypes.byref(scalar))
            if hr!=S_OK:return None
            return {"percent":max(0,min(100,round(float(scalar.value)*100)))}
        if action=="get_mute":
            hr=_com_method(endpoint,15,ctypes.c_long,[ctypes.POINTER(ctypes.c_int)],ctypes.byref(mute)); return bool(mute.value) if hr==S_OK else None
        if action=="set":
            level=max(0,min(100,int(value)))/100.0
            hr=_com_method(endpoint,7,ctypes.c_long,[ctypes.c_float,ctypes.c_void_p],ctypes.c_float(level),None)
            if hr!=S_OK:return None
            scalar2=ctypes.c_float(); hr=_com_method(endpoint,9,ctypes.c_long,[ctypes.POINTER(ctypes.c_float)],ctypes.byref(scalar2))
            return max(0,min(100,round(float(scalar2.value)*100))) if hr==S_OK else None
        if action=="mute":
            hr=_com_method(endpoint,14,ctypes.c_long,[ctypes.c_int,ctypes.c_void_p],1,None); return hr==S_OK
        if action=="unmute":
            hr=_com_method(endpoint,14,ctypes.c_long,[ctypes.c_int,ctypes.c_void_p],0,None); return hr==S_OK
        return None
    except Exception as error:
        print("CORE AUDIO ERROR:",repr(error)); return None
    finally:
        _release_com(endpoint); _release_com(device); _release_com(enumerator)
        if initialized:
            ole32.CoUninitialize()


def _command14_volume(text):
    relevant=("volume" in text or "sound volume" in text or "system volume" in text)
    if not relevant:return False
    current=_command14_audio_volume("get")
    if not current:
        speak("I couldn't read the Windows system volume."); return True
    if any(x in text for x in ("show","what is","check","tell me")) and not any(x in text for x in ("increase","decrease","raise","lower","set")):
        speak(f"Your system volume is {current['percent']} percent."); _command14_show_level("Volume",current['percent']); return True
    if "mute" in text and "unmute" not in text:
        ok=_command14_audio_volume("mute"); speak("System volume is muted." if ok else "I couldn't mute the system volume."); return True
    if "unmute" in text:
        ok=_command14_audio_volume("unmute"); speak("System volume is unmuted." if ok else "I couldn't unmute the system volume."); return True
    value=_command14_extract_percent(text)
    cur=current['percent']
    if re.search(r"\b(?:increase|raise)\b",text): value=cur+(value if value is not None else 10)
    elif re.search(r"\b(?:decrease|lower)\b",text): value=cur-(value if value is not None else 10)
    elif re.search(r"\bset\b",text) and value is None:
        speak("Please tell me the volume percentage."); return True
    elif value is None:
        speak(f"Your system volume is {cur} percent."); _command14_show_level("Volume",cur); return True
    actual=_command14_audio_volume("set",value)
    if actual is None:
        speak("I couldn't change the real Windows system volume."); return True
    speak(f"System volume is now {actual} percent."); _command14_show_level("Volume",actual); return True


# ---------------------- System information ----------------------
def _command14_system_data_raw():
    # Emit one JSON object so device names containing punctuation cannot corrupt the parser.
    script=r'''$cs=Get-CimInstance Win32_ComputerSystem; $os=Get-CimInstance Win32_OperatingSystem; $cpu=Get-CimInstance Win32_Processor | Select-Object -First 1; $gpu=@(Get-CimInstance Win32_VideoController); $ram=[math]::Round($cs.TotalPhysicalMemory/1GB,1); $dr=@(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"); $storage=@($dr | ForEach-Object { [pscustomobject]@{Drive=$_.DeviceID;SizeGB=[math]::Round($_.Size/1GB,1);FreeGB=[math]::Round($_.FreeSpace/1GB,1)} }); $g=@($gpu | ForEach-Object {$_.Name}); $res=@($gpu | Where-Object {$_.CurrentHorizontalResolution -and $_.CurrentVerticalResolution} | Select-Object -First 1 | ForEach-Object {"$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)"}); $n=@(Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object {$_.FriendlyName -match 'NPU|Neural Processing|AI Boost|Hexagon|Ryzen AI'} | Select-Object -ExpandProperty FriendlyName -Unique); $audio=@(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name -Unique); $load=[int](Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average; $used=[math]::Round((($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize)*100,1); [pscustomobject]@{Brand=$cs.Manufacturer;Model=$cs.Model;RAMGB=$ram;OS=("$($os.Caption) $($os.Version)");CPU=$cpu.Name;GPU=$g;NPU=$n;Audio=$audio;Storage=$storage;Display=($res -join ', ');CPUUsage=$load;MemoryUsage=$used} | ConvertTo-Json -Compress'''
    r=_command14_powershell(script,15)
    if not r:return {}
    try:
        data=json.loads(r)
        data["RAM"]=data.pop("RAMGB", "unknown")
        data["DISPLAY"]=data.pop("Display", "unknown")
        data["PERFORMANCE"]=f"CPU {data.pop('CPUUsage','unknown')} percent, memory {data.pop('MemoryUsage','unknown')} percent"
        storage=data.pop("Storage",[])
        if isinstance(storage,dict): storage=[storage]
        data["STORAGE"]=", ".join(f"{x.get('Drive','')}: {x.get('SizeGB','?')} GB total, {x.get('FreeGB','?')} GB free" for x in storage) if storage else "unknown"
        for key in ("GPU","NPU","Audio"):
            if isinstance(data.get(key),list): data[key]="; ".join(str(x) for x in data[key]) or "none reported"
        return {"BRAND":data.get("Brand") or "unknown","MODEL":data.get("Model") or "unknown","RAM":data.get("RAM") or "unknown","OS":data.get("OS") or "unknown","CPU":data.get("CPU") or "unknown","GPU":data.get("GPU") or "unknown","NPU":data.get("NPU") or "none reported","AUDIO":data.get("Audio") or "unknown","STORAGE":data.get("STORAGE") or "unknown","DISPLAY":data.get("DISPLAY") or "unknown","PERFORMANCE":data.get("PERFORMANCE") or "unknown"}
    except Exception as error:
        print("SYSTEM DATA PARSE ERROR:",repr(error))
        return {}


def _command14_system_data(text):
    # Only answer a specific field when the user asks for that field. Full output is
    # reserved for explicit "full/complete system information" requests.
    wants_full=any(x in text for x in ("full system information","complete system information","all system information","system information"))
    data=None
    def get(k):
        nonlocal data
        if data is None:data=_command14_system_data_raw()
        return data.get(k,"unknown") or "unknown"
    if "laptop brand" in text or "computer brand" in text or "brand" in text and "laptop" in text:
        speak(f"Your laptop brand is {get('BRAND')}."); return True
    if "laptop model" in text or "computer model" in text or "model" in text and ("laptop" in text or "computer" in text):
        speak(f"Your laptop model is {get('MODEL')}."); return True
    if "ram" in text or "memory" in text:
        speak(f"Your RAM is {get('RAM')} gigabytes."); return True
    if "storage" in text or "disk space" in text:
        speak(f"Your storage is {get('STORAGE')}."); return True
    if "graphics card" in text or "gpu" in text or "graphics processor" in text:
        speak(f"Your graphics processor is {get('GPU')}."); return True
    if "npu" in text or "neural processing" in text or "ai processor" in text:
        speak(f"Your NPU information is {get('NPU')}."); return True
    if "windows version" in text or "operating system" in text or text=="os information":
        speak(f"Your operating system is {get('OS')}."); return True
    if "processor" in text or "cpu" in text:
        speak(f"Your processor is {get('CPU')}."); return True
    if "audio" in text or "speaker" in text or "sound device" in text:
        speak(f"Your audio devices are {get('AUDIO')}."); return True
    if "display" in text or "screen resolution" in text or "screen size" in text:
        speak(f"Your display information is {get('DISPLAY')}."); return True
    if "performance" in text or "cpu usage" in text or "memory usage" in text:
        speak(f"Your current performance is {get('PERFORMANCE')}."); return True
    if "generation" in text and ("processor" in text or "cpu" in text):
        cpu=get('CPU').lower()
        match=re.search(r"(?:i[3579])-?(\d{4,5})",cpu)
        if match:
            digits=match.group(1)
            gen=digits[:-3] if len(digits)==5 else digits[0]
            speak(f"Your processor is approximately {gen}th generation.")
        elif "ryzen" in cpu:
            speak(f"Your processor is {get('CPU')}. AMD does not use the same Intel generation naming system.")
        else:
            speak(f"Your processor is {get('CPU')}.")
        return True
    if "system information" in text and wants_full:
        speak(f"Brand: {get('BRAND')}. Model: {get('MODEL')}. RAM: {get('RAM')} gigabytes. Storage: {get('STORAGE')}. Graphics: {get('GPU')}. NPU: {get('NPU')}. Operating system: {get('OS')}. Processor: {get('CPU')}. Display: {get('DISPLAY')}.")
        return True
    return False


# ---------------------- Command 14 router ----------------------
def handle_command14(command):
    global SETTINGS_OPENED
    text=_command14_fix_app_transcript(command)

    # A generic request to open/list applications must ask which app the user means.
    # It must not launch YouTube (or any other app) without an application name.
    if text in {"open applications", "open application", "open apps", "show applications", "show apps", "list applications", "list apps"}:
        speak("Which application would you like me to open?")
        return True

    # Windows Search / Start.
    if text in {"open windows search","open windows search bar","open search bar","open laptop search","open computer search"}:
        _command14_open_windows_search(); speak("I opened Windows Search."); return True
    if text in {"open start menu","open windows start","open start","open windows menu"}:
        _command14_open_start_menu(); speak("I opened the Start menu."); return True
    q=_command14_extract_laptop_search(text)
    if q:return _command14_search_laptop(q)

    # Settings phrases. Specific pages are checked before generic Settings.
    settings_phrases={
        "open settings":"home","settings":"home","open windows settings":"home",
        "open sound settings":"sound","sound settings":"sound","open location settings":"location","location settings":"location",
        "open bluetooth settings":"bluetooth","bluetooth settings":"bluetooth","open display settings":"display","display settings":"display",
        "open notification settings":"notifications","notification settings":"notifications","open focus settings":"focus","focus settings":"focus",
        "open storage settings":"storage","storage settings":"storage","open share settings":"share","share settings":"share",
        "open multitasking settings":"multitasking","multitasking settings":"multitasking","open ai components settings":"ai components","ai components settings":"ai components",
        "open system components settings":"system components","system components settings":"system components","open clipboard settings":"clipboard","clipboard settings":"clipboard",
        "open remote desktop settings":"remote desktop","remote desktop settings":"remote desktop","open recovery settings":"recovery","recovery settings":"recovery",
        "open windows update settings":"windows update","windows update settings":"windows update","open microsoft 365 settings":"microsoft 365","open onedrive settings":"onedrive",
        "open usb settings":"usb","usb settings":"usb","open autoplay settings":"autoplay","autoplay settings":"autoplay","open pen and windows ink settings":"pen and windows ink",
        "open touchpad settings":"touchpad","touchpad settings":"touchpad","open keyboard settings":"keyboard","keyboard settings":"keyboard","open mouse settings":"mouse","mouse settings":"mouse",
        "open mobile device settings":"mobile devices","mobile device settings":"mobile devices","mobile devices settings":"mobile devices","open camera settings":"cameras","camera settings":"cameras",
        "open wifi settings":"wifi","wifi settings":"wifi","open wi fi settings":"wi fi","wi fi settings":"wi fi","open vpn settings":"vpn","vpn settings":"vpn",
        "open mobile hotspot settings":"mobile hotspot","mobile hotspot settings":"mobile hotspot","open airplane mode settings":"airplane mode","airplane mode settings":"airplane mode","open proxy settings":"proxy","proxy settings":"proxy",
        "open dial up settings":"dial up","dial up settings":"dial up","open advanced network settings":"advanced network settings","advanced network settings":"advanced network settings",
        "open background settings":"background","background settings":"background","open colors settings":"colors","colors settings":"colors","open themes settings":"themes","themes settings":"themes",
        "open dynamic lighting settings":"dynamic lighting","dynamic lighting settings":"dynamic lighting","open lock screen settings":"lock screen","lock screen settings":"lock screen","open text input settings":"text input","text input settings":"text input",
        "open fonts settings":"fonts","fonts settings":"fonts","open taskbar settings":"taskbar","taskbar settings":"taskbar",
        "open installed apps settings":"installed apps","installed apps settings":"installed apps","open advanced apps settings":"advanced apps settings","advanced apps settings":"advanced apps settings",
        "open default apps settings":"default apps","default apps settings":"default apps","open offline maps settings":"offline maps","offline maps settings":"offline maps","open apps for websites settings":"apps for websites","apps for websites settings":"apps for websites",
        "open accounts settings":"accounts","account settings":"account","accounts settings":"accounts","open time and language settings":"time and language","time and language settings":"time and language",
        "open gaming settings":"gaming","gaming settings":"gaming","open accessibility settings":"accessibility","accessibility settings":"accessibility",
        "open privacy settings":"privacy","privacy settings":"privacy","open privacy and security settings":"privacy and security","privacy and security settings":"privacy and security",
        "open battery settings":"battery","battery settings":"battery","open power settings":"power","power settings":"power",
        "system settings":"system","open system settings":"system","devices settings":"devices","open devices settings":"devices","network and internet settings":"network and internet",
        "open network and internet settings":"network and internet","personalization settings":"personalization","open personalization settings":"personalization","apps settings":"apps","open apps settings":"apps",
    }
    if text in settings_phrases:
        section=settings_phrases[text]; uri=SETTINGS_SECTION_URIS.get(section,"")
        if _command14_open_settings(uri):
            speak("I opened Windows Settings." + (f" {section} settings." if section!="home" else ""))
        else:speak("I couldn't open that Windows Settings page.")
        return True
    if text in {"go back","back","go back in settings","back in settings","back out","back out of settings","settings back","go back from settings","go back to settings","previous settings page","go to previous page","previous page"}:
        ok=_command14_send_alt_left()
        speak("I went back one page." if ok else "I couldn't go back.")
        return True
    if text in {"close settings","exit settings","close windows settings"}:
        return _command14_close_settings()

    # Browser search.
    q=_command14_extract_search_query(text)
    if q:return _command14_search_browser(q)
    if text in {"search","search google","open google","open browser","open web browser","browser","google"}:
        return _command14_search_browser("")

    # System data before battery/brightness/volume.
    if _command14_system_data(text):return True

    if any(x in text for x in ("battery","charging","plugged in","power status")):
        return _command14_battery_answer(text)
    if _command14_brightness(text):return True
    if _command14_volume(text):return True

    close_match=re.match(r"^(?:close|quit|exit|terminate)\s+(.+)$",text)
    if close_match:
        target=close_match.group(1).strip()
        target=re.sub(r"\s+(?:application|app|program|window)$", "", target).strip()
        if target in {"this", "this app", "this window", "current app", "current window", "window", "windows", "active window"}:
            ok=_command14_send_alt_f4()
            speak("I closed the current window." if ok else "I couldn't close the current window.")
            return True
        if target in {"settings","windows settings"}:
            return _command14_close_settings()
        app_key=APP_ALIASES.get(target)
        if app_key:
            return _command14_close_app(app_key)
        speak(f"I don't recognize the application {target}, so I haven't closed anything.")
        return True
    if text in {"close application", "close applications", "close app", "close apps", "close this application"}:
        ok=_command14_send_alt_f4()
        speak("I closed the current window." if ok else "I couldn't close the current window.")
        return True

    open_match=re.match(r"^(?:open|launch|start|run)\s+(.+)$",text)
    if open_match:
        target=open_match.group(1).strip()
        # Accept natural variants like “open Paint application” without treating
        # the app name as a generic web search or accidentally opening YouTube.
        target=re.sub(r"\s+(?:application|app)$", "", target).strip()
        app_key=APP_ALIASES.get(target)
        if app_key:
            return _command14_open_app(app_key)
        if target in {"settings", "windows settings"}:
            if _command14_open_settings(""):
                speak("I opened Windows Settings.")
            else:
                speak("I couldn't open Windows Settings.")
            return True
        # Do not route an unrecognized application name to browser/YouTube search.
        speak(f"I couldn't find an application named {target}. Please say the application name again.")
        return True

    return False

# ---------------------- Command 15: Music search and recognition ----------------------

def _music_open_youtube(query):
    """Open a YouTube results page once; do not also trigger Spotify or browser search."""
    import webbrowser
    query = str(query or "").strip()
    if not query:
        speak("Please tell me a song title, singer name, or movie name.")
        return True
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})
    try:
        opened = webbrowser.open(url, new=2)
        if opened:
            speak(f"Opening YouTube results for {query}.")
        else:
            # webbrowser may return False even when Windows hands the URL off successfully.
            os.startfile(url)
            speak(f"Opening YouTube results for {query}.")
    except Exception as error:
        print("YOUTUBE MUSIC OPEN ERROR:", repr(error))
        try:
            os.startfile(url)
            speak(f"Opening YouTube results for {query}.")
        except Exception as second_error:
            print("YOUTUBE MUSIC FALLBACK ERROR:", repr(second_error))
            speak("I couldn't open YouTube. Please check your default browser and internet connection.")
    return True


def _music_extract_query(raw_command):
    """Return (kind, query) for clear song, artist, or movie requests."""
    raw = str(raw_command or "").strip()
    # Work on an ASCII-normalized copy for command framing, but extract the query from raw
    # text so song titles in Telugu, Hindi, Korean, Japanese, etc. are preserved.
    norm = normalize_command(raw)
    norm = re.sub(r"^(?:hey|hi|hello)\s+", "", norm)
    norm = re.sub(r"^(?:sara|sarah|tara|saraa)\s+", "", norm)

    patterns = [
        ("identify", r"^(?:identify|recognize|recognise|detect|find) (?:this |the )?(?:song|music|audio|track)(?: playing)?$"),
        ("identify", r"^(?:what song is this|which song is this|what is this song|what song is playing|which song is playing|name this song|tell me this song|listen to this song|identify this audio)$"),
        ("movie", r"^(?:play|search|find|open) (?:the )?(?:songs|song) from (?:the movie )?(.+?)(?: on youtube)?$"),
        ("movie", r"^(?:play|search|find|open) (.+?) movie songs(?: on youtube)?$"),
        ("artist", r"^(?:play|search|find|open) (?:the )?songs by (.+?)(?: on youtube)?$"),
        ("artist", r"^(?:play|search|find|open) (.+?) songs(?: by the singer)?(?: on youtube)?$"),
        ("artist", r"^(?:play|search|find|open) (.+?) singer(?: songs)?(?: on youtube)?$"),
        ("song", r"^(?:play|search|find|open) (?:the )?song (.+?)(?: on youtube)?$"),
        ("song", r"^(?:play|search|find|open) (.+?) song(?: on youtube)?$"),
        ("generic", r"^(?:play|search|find) (.+?)(?: on youtube| on youtube music)?$"),
        ("generic", r"^(?:play|put on) (.+)$"),
    ]
    match = None
    kind = ""
    for candidate_kind, pattern in patterns:
        m = re.match(pattern, norm, flags=re.IGNORECASE)
        if m:
            match, kind = m, candidate_kind
            break
    if not match:
        # Unicode-only titles can disappear from the ASCII framing copy. Still accept
        # an explicit play request from the original transcript without altering its title.
        raw_fallback = raw
        raw_fallback = re.sub(r"^(?:(?:hey|hi|hello)\s+)?(?:sara|sarah|tara|saraa)[,\s]+", "", raw_fallback, flags=re.IGNORECASE)
        m_raw = re.match(r"^(?:play|put on)\s+(.+)$", raw_fallback, flags=re.IGNORECASE)
        if m_raw and m_raw.group(1).strip():
            fallback_query = m_raw.group(1).strip()
            fallback_query = re.sub(r"\s+on\s+youtube(?:\s+music)?\s*$", "", fallback_query, flags=re.IGNORECASE)
            return "generic", fallback_query.strip(" \\t\\r\\n\"'.,!?-")
        return "", ""

    # Extract the corresponding phrase from the original transcript. First remove wake word
    # and leading action words while preserving all Unicode characters in the title.
    raw_query = raw
    raw_query = re.sub(r"^(?:(?:hey|hi|hello)\s+)?(?:sara|sarah|tara|saraa)[,\s]+", "", raw_query, flags=re.IGNORECASE)
    raw_query = re.sub(r"^(?:play|search|find|open|put on)\s+", "", raw_query, flags=re.IGNORECASE)
    raw_query = re.sub(r"\s+on\s+youtube(?:\s+music)?\s*$", "", raw_query, flags=re.IGNORECASE)
    raw_query = re.sub(r"^the\s+", "", raw_query, flags=re.IGNORECASE)

    # Strip framing suffixes from the original text; these suffixes are English command words,
    # while the actual title/name may be in any script.
    # Remove leading relationship phrases from the original transcript too.
    raw_query = re.sub(r"^(?:the\s+)?(?:songs|song)\s+from\s+(?:the\s+movie\s+)?", "", raw_query, flags=re.IGNORECASE)
    raw_query = re.sub(r"^(?:the\s+)?songs\s+by\s+(?:singer\s+)?", "", raw_query, flags=re.IGNORECASE)
    raw_query = re.sub(r"^(?:the\s+)?song\s+", "", raw_query, flags=re.IGNORECASE)
    suffixes = [
        r"\s+movie\s+songs\s*$", r"\s+singer(?:\s+songs)?\s*$",
        r"\s+song\s*$", r"\s+songs\s*$",
    ]
    for suffix in suffixes:
        raw_query = re.sub(suffix, "", raw_query, flags=re.IGNORECASE)
    raw_query = raw_query.strip(" \t\r\n\"'.,!?-")
    # For explicit movie phrasing, normalize the query so YouTube finds soundtrack videos.
    if kind == "movie":
        raw_query = f"{raw_query} movie songs".strip()
    elif kind == "artist":
        raw_query = f"{raw_query} songs".strip()
    elif kind == "song":
        raw_query = f"{raw_query} song".strip()
    return kind, raw_query


def _music_identify_audio():
    """Record a fixed 20-second microphone sample and identify it with ShazamIO."""
    if MUSIC_RECOGNIZER is None or MUSIC_MICROPHONE is None:
        speak("Audio recognition is not ready because the microphone is unavailable.")
        return True

    try:
        import asyncio
        from io import BytesIO
        from shazamio import Shazam
    except ImportError as error:
        print("SHAZAMIO IMPORT ERROR:", repr(error))
        speak("Audio recognition is not ready. Please check that ShazamIO is installed in Sara's active environment.")
        return True

    speak("Okay, I'm listening to the song or background music for twenty seconds. Please keep it playing near the microphone.")
    try:
        # record(duration=12) captures a fixed-length sample and does NOT wait for
        # speech energy. This is important because songs/background music are not speech.
        with MUSIC_MICROPHONE as source:
            print("MUSIC CAPTURE: device=", getattr(source, "device_index", None),
                  "sample_rate=", source.SAMPLE_RATE, "seconds=20")
            audio_data = MUSIC_RECOGNIZER.record(source, duration=20)

        # ShazamIO needs encoded audio-file bytes. AudioData.get_wav_data creates a WAV.
        wav_bytes = audio_data.get_wav_data(convert_rate=44100, convert_width=2)
        print("MUSIC CAPTURE: WAV bytes=", len(wav_bytes))
        if not wav_bytes:
            speak("I couldn't prepare the audio sample. Please try again.")
            return True

        async def _recognize():
            # ShazamIO's Shazam instance is not an async context manager in the
            # installed version. Instantiate it normally and await recognize().
            shazam = Shazam()
            return await shazam.recognize(wav_bytes)

        result = asyncio.run(_recognize())
        print("SHAZAMIO RESPONSE TYPE:", type(result).__name__)
        track = result.get("track") if isinstance(result, dict) else None
        if not isinstance(track, dict):
            matches = result.get("matches", []) if isinstance(result, dict) else []
            if matches and isinstance(matches[0], dict):
                track = matches[0].get("track", matches[0])

        if not isinstance(track, dict) or not (track.get("title") or track.get("subtitle")):
            print("SHAZAMIO NO MATCH:", repr(result)[:1500])
            speak("I listened to the audio, but couldn't identify the song. Please try again with the music a little louder and clearer.")
            return True

        title = str(track.get("title", "")).strip()
        artist = str(track.get("subtitle", "")).strip()
        if not artist:
            artists = track.get("artists", [])
            if isinstance(artists, list):
                artist = ", ".join(str(a.get("name", "")) for a in artists if isinstance(a, dict) and a.get("name"))

        print("SONG IDENTIFIED:", title, "| ARTIST:", artist)
        speak(f"I identified the song as {title}" + (f" by {artist}" if artist else "") + ".")

        # Open YouTube search results for the identified track automatically.
        # Search results are safer than guessing a specific video URL.
        try:
            import webbrowser
            youtube_query = " ".join(part for part in (title, artist) if part).strip()
            youtube_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(youtube_query)
            opened = webbrowser.open(youtube_url, new=2)
            if opened:
                print("YOUTUBE OPENED:", youtube_query)
                speak("I'm opening it on YouTube now.")
            else:
                print("YOUTUBE OPEN REQUEST SENT:", youtube_url)
                speak("I found the song. Please check your browser for YouTube.")
        except Exception as browser_error:
            print("YOUTUBE OPEN ERROR:", repr(browser_error))
            speak("I identified the song, but couldn't open YouTube automatically.")
        return True

    except sr.WaitTimeoutError:
        # Retained for compatibility with existing SpeechRecognition error handling.
        speak("I didn't receive audio. Please try again while the song is playing.")
    except Exception as error:
        print("MUSIC IDENTIFICATION ERROR:", repr(error))
        speak("I couldn't identify that audio right now. Please check your internet connection and try again.")
    return True


def handle_command15(command):
    """Command 15: route music requests before app and browser handlers."""
    raw = LAST_RAW_TRANSCRIPT if LAST_RAW_TRANSCRIPT else str(command or "")
    kind, query = _music_extract_query(raw)
    normalized = normalize_command(raw)
    normalized = re.sub(r"^(?:(?:hey|hi|hello)\s+)?(?:sara|sarah|tara|saraa)[,\s]+", "", normalized)
    identify_phrases = {
        "identify this song", "recognize this song", "recognise this song", "what song is this",
        "which song is this", "what is this song", "what song is playing", "which song is playing",
        "name this song", "tell me this song", "listen to this song", "identify this audio",
        "recognize the song", "recognise the song", "detect this song", "find this song by listening",
        "identify this background music", "identify background music", "recognize background music",
        "recognise background music", "what is this background music", "what music is this",
        "identify this song or background music", "identify song or background music",
        "tell me the background music", "name the background music", "what song or background music is this",
    }
    # Also accept natural variations such as “Sara, identify this song or background music”.
    identify_request = (
        normalized in identify_phrases
        or (re.search(r"\b(identify|recognize|recognise|detect|name)\b", normalized)
            and re.search(r"\b(song|music|audio|track)\b", normalized))
        or (re.search(r"\b(what|which|tell me)\b", normalized)
            and re.search(r"\b(background music|song|music)\b", normalized)
            and re.search(r"\b(this|playing|play)\b", normalized))
    )
    if kind == "identify" or identify_request:
        return _music_identify_audio()
    if kind and query:
        return _music_open_youtube(query)
    return False


# ---------------------- Main command handler ----------------------

def handle_command(command):
    command = correct_assistant_name(command)
    command = normalize_command(command)
    command = strip_assistant_address(command)
    if not command:
        return True

    # Exit commands: keep these ahead of every other handler so Sara can
    # always stop when the user says bye, goodbye, or exit.
    exit_commands = {
        "bye", "goodbye", "good bye", "exit", "quit", "stop",
        "bye sara", "goodbye sara", "good bye sara", "exit sara",
        "quit sara", "stop sara", "close sara", "stop listening",
    }
    if command in exit_commands:
        goodbye_name = get_user_nickname() or get_user_name()
        if goodbye_name:
            speak(f"Goodbye {goodbye_name}, take care. Call me when you need me.")
        else:
            speak("Goodbye, take care. Call me when you need me.")
        return False

    # Handle affection phrases FIRST, before memory or other command handlers.
    # This prevents phrases such as "I love you" and "I like you" from
    # accidentally being treated as facts to save in memory.
    preferred_name = get_user_nickname() or get_user_name()
    address = f", {preferred_name}" if preferred_name else ""
    affection_responses = {
        "i love you": f"Aww, that's really sweet of you{address}. I'm your virtual companion, and I'm happy to share a warm moment with you.",
        "i hate you": f"Oh no{address}. Did I do something wrong? Tell me what happened, and I'll try to make it right.",
        "i miss you": f"Aww{address}, it's nice to have you back. I'm here to chat with you.",
        "i like you": f"That's so sweet of you{address}. I enjoy being your friendly AI companion.",
        "i hug you": f"Aww{address}, sending you a big, warm virtual hug.",
        "i kiss you": f"Aww, that's affectionate of you{address}. I'll send you a sweet virtual smile.",
    }
    affection_aliases = {
        "i love u": "i love you",
        "love you": "i love you",
        "i hate u": "i hate you",
        "i miss u": "i miss you",
        "miss you": "i miss you",
        "i like u": "i like you",
        "i hug u": "i hug you",
        "i kiss u": "i kiss you",
    }
    command = affection_aliases.get(command, command)
    if command in affection_responses:
        speak(affection_responses[command])
        return True

    # Command 15: music search and audio recognition. Checked first to prevent
    # music requests from being misrouted to app-opening or generic search handlers.
    if handle_command15(command):
        return True

    # Command 12: offline Spiritual & Religious Knowledge Center.
    if handle_command12(command):
        return True

    # Command 14: applications, browser search, Settings, battery, brightness, and volume.
    if handle_command14(command):
        return True

    # Command 13: GPS, current location, live tracking, and WhatsApp sharing.
    if handle_command13(command):
        return True

    # Command 11: offline Technology Knowledge Center.
    # Check technology before weather so cloud-computing questions are never
    # misclassified as weather/cloud-condition questions.
    if handle_command11(command):
        return True

    # Command 7: time, calendar, weather, and seasons.
    if handle_command7(command):
        return True

    # Command 10: offline programming languages, data science, and language-based jobs.
    if handle_command10(command):
        return True

    # Command 9: offline Artificial Intelligence knowledge center.
    if handle_command9(command):
        return True

    # Command 8: offline general knowledge.
    if handle_command8(command):
        return True

    # Command 5 calculations are checked before chat and memory handlers.
    if handle_calculation_command(command):
        return True

    if handle_voice_command(command):
        return True

    # Identity commands (accept "your self" and "yourself")
    if command in {"who are you", "introduce yourself", "introduce your self",
                   "who are you sara", "introduce yourself sara"}:
        speak("I am Sara 2.0, your female voice assistant. I can remember personal details, favorites, education and relationships, answer questions about saved information, and switch between my installed female voices.")
        return True

    if command in {"what can you do", "what can you do sara", "help me", "your features"}:
        speak("I can remember personal details, switch voices, calculate, tell time and dates, and look up current or historical weather, forecasts, and seasonal information.")
        return True

    if handle_chat_command(command):
        return True

    if command in {"test voice", "speak", "say something"}:
        test_name = get_user_nickname() or get_user_name()
        speak(f"Hello {test_name}! My voice is working." if test_name else "Hello! My voice is working.")
        return True

    if command in {"what is your name", "what's your name"}:
        speak("I am Sara 2.0, your female voice assistant.")
        return True

    result = handle_memory_command(command)
    if result in {"handled", "confirm_all"}:
        return True

    # Keep the two fallback responses distinct: recognizable questions get the
    # unknown-answer response; other unhandled utterances get the not-understood response.
    fallback_name = get_user_nickname() or get_user_name()
    question_like = bool(re.search(
        r"\b(what|who|whom|whose|when|where|why|how|which|is|are|am|was|were|do|does|did|can|could|would|will|should|has|have|had)\b",
        command,
    )) or command.endswith("?")
    if question_like:
        response = "I don't have an answer for it, but I'll learn for you"
    else:
        response = "I don't understand what you're saying"
    if fallback_name:
        response += f", {fallback_name}"
    speak(response + ".")
    return True


def main():
    global MUSIC_RECOGNIZER, MUSIC_MICROPHONE
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.8
    recognizer.non_speaking_duration = 0.8
    recognizer.operation_timeout = 12
    recognizer.dynamic_energy_threshold = True

    try:
        # Device 1 was the microphone that successfully captured audio in earlier
        # Sara tests. Respect SARA_MIC_DEVICE_INDEX if the user later needs another one.
        # If the selected index is unavailable, safely fall back to Windows' default.
        import os
        device_setting = os.environ.get("SARA_MIC_DEVICE_INDEX", "1").strip()
        try:
            device_index = int(device_setting) if device_setting else None
            if device_index is not None:
                device_names = sr.Microphone.list_microphone_names()
                if device_index < 0 or device_index >= len(device_names):
                    device_index = None
            microphone = sr.Microphone(device_index=device_index)
            print("SARA MICROPHONE:", device_index, device_names[device_index] if device_index is not None else "Windows default")
        except Exception as device_error:
            print("PREFERRED MICROPHONE UNAVAILABLE; using default:", repr(device_error))
            microphone = sr.Microphone()
        MUSIC_RECOGNIZER = recognizer
        MUSIC_MICROPHONE = microphone
    except Exception as error:
        print("MICROPHONE ERROR:", repr(error))
        input("Press Enter to close...")
        return

    try:
        with microphone as source:
            print("Calibrating microphone...")
            recognizer.adjust_for_ambient_noise(source, duration=1)

        smart_personal_greeting()

        while True:
            command = listen(recognizer, microphone)
            if command:
                if not handle_command(command):
                    break
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nSara stopped.")
    except Exception as error:
        print("ASSISTANT ERROR:", repr(error))
    print("Sara 2.0 has stopped.")


if __name__ == "__main__":
    main()
