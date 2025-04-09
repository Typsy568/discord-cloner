
from flask import Flask, render_template, request, Response, stream_with_context
import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

def safe_post(url, headers, data, name="item", retries=3, delay=1.5):
    for attempt in range(retries):
        r = requests.post(url, headers=headers, json=data)
        if r.status_code == 429:
            retry_after = r.json().get("retry_after", delay)
            print(f"[RATE LIMIT] Waiting {retry_after}s for {name}...")
            time.sleep(retry_after)
        elif r.status_code in [200, 201]:
            return r
        else:
            print(f"[FAIL] Could not create {name}: {r.status_code}")
            return r
    return r

app = Flask(__name__)
DISCORD_API = "https://discord.com/api/v10"

def stream_events(source_id, dest_id, token):
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    def send(message):
        print("[DEBUG]", message)
        yield f"data: {message}\n\n"

    # Validate source guild
    guild_check = requests.get(f"{DISCORD_API}/guilds/{source_id}", headers=headers)
    if guild_check.status_code != 200:
        yield from send("❌ Invalid source server ID or missing permissions.")
        yield from send("[DONE]")
        return

    yield from send("🔒 Authenticating and fetching data...")

    # Delete destination channels
    dest_channels = requests.get(f"{DISCORD_API}/guilds/{dest_id}/channels", headers=headers).json()
    for ch in dest_channels:
        resp = requests.delete(f"{DISCORD_API}/channels/{ch['id']}", headers=headers)
        msg = f"🧹 Deleted channel: {ch['name']}" if resp.status_code == 200 else f"⚠️ Failed to delete channel: {ch['name']}"
        yield from send(msg)

    # Delete destination roles
    dest_roles = requests.get(f"{DISCORD_API}/guilds/{dest_id}/roles", headers=headers).json()
    for role in sorted(dest_roles, key=lambda x: x["position"], reverse=True):
        if role["name"] == "@everyone" or role.get("managed"):
            continue
        resp = requests.delete(f"{DISCORD_API}/guilds/{dest_id}/roles/{role['id']}", headers=headers)
        msg = f"🧹 Deleted role: {role['name']}" if resp.status_code == 204 else f"⚠️ Failed to delete role: {role['name']}"
        yield from send(msg)

    # Clone roles
    roles = requests.get(f"{DISCORD_API}/guilds/{source_id}/roles", headers=headers).json()
    role_map = {}
    yield from send(f"📥 Found {len(roles)} roles to clone.")
    for role in reversed(roles):
        if role["name"] == "@everyone":
            continue
        data = {
            "name": role["name"],
            "color": role["color"],
            "hoist": role["hoist"],
            "mentionable": role["mentionable"],
            "permissions": role["permissions"]
        }
        r = safe_post(f"{DISCORD_API}/guilds/{dest_id}/roles", headers, data, role["name"])
        if r.status_code in [200, 201]:
            new_role = r.json()
            role_map[role["id"]] = new_role["id"]
            yield from send(f"✅ Created role: {role['name']}")
        else:
            yield from send(f"❌ Failed role: {role['name']} ({r.status_code})")

    # Clone categories
    source_channels = requests.get(f"{DISCORD_API}/guilds/{source_id}/channels", headers=headers).json()
    cat_map = {}
    categories = [c for c in source_channels if c["type"] == 4]
    yield from send(f"📁 Cloning {len(categories)} categories...")
    for cat in categories:
        data = {
            "name": cat["name"],
            "type": 4,
            "permission_overwrites": cat.get("permission_overwrites", [])
        }
        r = safe_post(f"{DISCORD_API}/guilds/{dest_id}/channels", headers, data, cat["name"])
        if r.status_code in [200, 201]:
            new_cat = r.json()
            cat_map[cat["id"]] = new_cat["id"]
            yield from send(f"📂 Created category: {cat['name']}")
        else:
            yield from send(f"⚠️ Failed category: {cat['name']}")

    # Clone regular channels
    channels = [c for c in source_channels if c["type"] != 4]
    yield from send(f"📺 Cloning {len(channels)} channels...")
    for ch in channels:
        data = {
            "name": ch["name"],
            "type": ch["type"],
            "topic": ch.get("topic"),
            "nsfw": ch.get("nsfw", False),
            "bitrate": ch.get("bitrate"),
            "user_limit": ch.get("user_limit"),
            "rate_limit_per_user": ch.get("rate_limit_per_user", 0),
            "parent_id": cat_map.get(ch.get("parent_id")),
            "permission_overwrites": ch.get("permission_overwrites", [])
        }
        data = {k: v for k, v in data.items() if v is not None}
        r = safe_post(f"{DISCORD_API}/guilds/{dest_id}/channels", headers, data, ch["name"])
        if r.status_code in [200, 201]:
            yield from send(f"✅ Created channel: {ch['name']}")
        else:
            yield from send(f"❌ Failed channel: {ch['name']} ({r.status_code})")

    yield from send("✅ Cloning finished successfully.")
    yield from send("[DONE]")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/clone-stream")
def clone_stream():
    source = request.args.get("source")
    dest = request.args.get("dest")
    token = request.args.get("token")
    return Response(stream_with_context(stream_events(source, dest, token)), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True)
