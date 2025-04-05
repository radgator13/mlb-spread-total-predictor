import streamlit as st
import pandas as pd
import requests
from datetime import date
import math

st.set_page_config(layout="wide")

# --- Configuration ---
API_KEY = 'YOUR_API_KEY'  # Replace with your Odds API key
SPORT = 'baseball_mlb'
REGIONS = 'us'
MARKETS = 'spreads,totals'
ODDS_FORMAT = 'american'

# --- Cached API fetch ---
@st.cache_data(ttl=3600)
def fetch_json(url, headers=None):
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"Error fetching: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_schedule(selected_date):
    d = selected_date.strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
    data = fetch_json(url)
    games = []
    for game in data.get('dates', [{}])[0].get('games', []):
        games.append({
            'game_id': game['gamePk'],
            'away': game['teams']['away']['team']['name'],
            'home': game['teams']['home']['team']['name'],
            'home_id': game['teams']['home']['team']['id'],
            'away_id': game['teams']['away']['team']['id']
        })
    return pd.DataFrame(games)

def get_probable_pitchers(game_id):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"
    data = fetch_json(url)
    pp = data.get('gameData', {}).get('probablePitchers', {})
    return {
        'home': pp.get('home', {}).get('id'),
        'away': pp.get('away', {}).get('id'),
        'home_name': pp.get('home', {}).get('fullName', 'N/A'),
        'away_name': pp.get('away', {}).get('fullName', 'N/A'),
    }

@st.cache_data(ttl=3600)
def fetch_stats(player_id, group):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=career&group={group}"
    data = fetch_json(url)
    if data.get('stats'):
        return data['stats'][0].get('splits', [{}])[0].get('stat', {})
    return {}

def pitcher_score(stat):
    try:
        era = float(stat.get('era', 5.0))
        k9 = float(stat.get('strikeoutsPer9Inn', 6.0))
        bb9 = float(stat.get('walksPer9Inn', 3.0))
        score = (5.0 - era) * 12 + (k9 - 6.0) * 8 + (3.0 - bb9) * 5
        return max(0, min(100, score))
    except:
        return 50

@st.cache_data(ttl=3600)
def fetch_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    data = fetch_json(url)
    return [p['person']['id'] for p in data.get('roster', [])]

def hitter_score(player_ids):
    scores = []
    for pid in player_ids:
        s = fetch_stats(pid, 'hitting')
        try:
            avg = float(s.get('avg', 0.250))
            obp = float(s.get('obp', 0.320))
            slg = float(s.get('slg', 0.400))
            val = (avg - 0.250) * 100 + (obp - 0.320) * 80 + (slg - 0.400) * 60
            scores.append(max(0, min(100, val)))
        except:
            continue
    return sum(scores) / len(scores) if scores else 50

# --- Vegas Odds ---
@st.cache_data(ttl=3600)
def fetch_vegas_lines():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds?regions={REGIONS}&markets={MARKETS}&oddsFormat={ODDS_FORMAT}&apiKey={API_KEY}"
    return fetch_json(url)

def extract_vegas_odds(vegas_data, home_team, away_team):
    for game in vegas_data:
        if game['home_team'] == home_team and game['away_team'] == away_team:
            spread, total = None, None
            for book in game.get('bookmakers', []):
                for market in book.get('markets', []):
                    if market['key'] == 'spreads':
                        for outcome in market['outcomes']:
                            if outcome['name'] == home_team:
                                spread = outcome['point']
                    if market['key'] == 'totals':
                        for outcome in market['outcomes']:
                            total = outcome['point']
            return spread, total
    return None, None

# --- Models ---
def predict_margin(home_p, away_p, home_h, away_h):
    return round((home_p - away_p) * 0.4 + (home_h - away_h) * 0.6, 2)

# 🔁 UPDATED TO FIX "Under every time" problem
def predict_total(home_p, away_p, home_h, away_h):
    return round((home_h + away_h) * 0.14 - (home_p + away_p) * 0.04 + 9.2, 2)



def confidence_score(edge):
    if edge is None:
        return "-"
    abs_edge = abs(edge)
    if abs_edge >= 2.0:
        return "🔥🔥🔥🔥🔥"
    elif abs_edge >= 1.5:
        return "🔥🔥🔥🔥"
    elif abs_edge >= 1.0:
        return "🔥🔥🔥"
    elif abs_edge >= 0.5:
        return "🔥🔥"
    else:
        return "🔥"

# --- Streamlit App ---
st.title("⚾ MLB Spread & Total Predictor with Smart Picks & Confidence")

selected_date = st.date_input("Select Game Date", date.today())
games_df = fetch_schedule(selected_date)

if games_df.empty:
    st.warning("No games found.")
    st.stop()

vegas_data = fetch_vegas_lines()
results = []
team_rosters = {}

def get_cached_roster(team_id):
    if team_id not in team_rosters:
        team_rosters[team_id] = fetch_roster(team_id)
    return team_rosters[team_id]

with st.spinner("Running model + Vegas comparison..."):
    progress = st.progress(0)

    for i, (_, game) in enumerate(games_df.iterrows()):
        try:
            game_id = game['game_id']
            matchup = f"{game['away']} @ {game['home']}"
            pitchers = get_probable_pitchers(game_id)

            if not pitchers['home'] or not pitchers['away']:
                progress.progress((i + 1) / len(games_df))
                continue

            home_p_stats = fetch_stats(pitchers['home'], 'pitching')
            away_p_stats = fetch_stats(pitchers['away'], 'pitching')
            home_p_score = pitcher_score(home_p_stats)
            away_p_score = pitcher_score(away_p_stats)

            home_roster = get_cached_roster(game['home_id'])
            away_roster = get_cached_roster(game['away_id'])
            home_h_score = hitter_score(home_roster)
            away_h_score = hitter_score(away_roster)

            model_margin = predict_margin(home_p_score, away_p_score, home_h_score, away_h_score)
            model_total = predict_total(home_p_score, away_p_score, home_h_score, away_h_score)

            vegas_spread, vegas_total = extract_vegas_odds(vegas_data, game['home'], game['away'])

            margin_edge = None if vegas_spread is None else round(model_margin - vegas_spread, 2)
            total_edge = None if vegas_total is None else round(model_total - vegas_total, 2)

            spread_pick = None
            total_pick = None

            if vegas_spread is not None:
                spread_pick = f"Home -{abs(vegas_spread)}" if model_margin > vegas_spread else f"Away +{abs(vegas_spread)}"

            if vegas_total is not None:
                total_pick = f"Over {vegas_total}" if model_total > vegas_total else f"Under {vegas_total}"

            results.append({
                "Matchup": matchup,
                "Model Margin (H - A)": model_margin,
                "Vegas Spread": vegas_spread,
                "Edge (Spread)": margin_edge,
                "Model Pick (Spread)": spread_pick,
                "Confidence (Spread)": confidence_score(margin_edge),
                "Model Total Runs": model_total,
                "Vegas Total": vegas_total,
                "Edge (Total)": total_edge,
                "Model Pick (Total)": total_pick,
                "Confidence (Total)": confidence_score(total_edge)
            })

            progress.progress((i + 1) / len(games_df))

        except Exception as e:
            st.error(f"❌ Error processing {game['away']} @ {game['home']}: {e}")
            continue

# --- Main Table ---
df = pd.DataFrame(results)
st.dataframe(df.reset_index(drop=True), use_container_width=True)

# --- Smart Picks Section: Best Edges ---
st.subheader("📌 Smart Picks vs Vegas Lines")

df_edges = df.dropna(subset=["Vegas Spread", "Vegas Total"])

spread_edges = df_edges.copy()
spread_edges["Edge (Spread Abs)"] = spread_edges["Edge (Spread)"].abs()
top_spread_picks = spread_edges.sort_values(by="Edge (Spread Abs)", ascending=False).head(5)

total_edges = df_edges.copy()
total_edges["Edge (Total Abs)"] = total_edges["Edge (Total)"].abs()
top_total_picks = total_edges.sort_values(by="Edge (Total Abs)", ascending=False).head(5)

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 🟢 Best Spread Picks")
    st.dataframe(
        top_spread_picks[
            ["Matchup", "Model Margin (H - A)", "Vegas Spread", "Edge (Spread)", 
             "Model Pick (Spread)", "Confidence (Spread)"]
        ].reset_index(drop=True),
        use_container_width=True
    )

with col2:
    st.markdown("#### 🔵 Best Total Picks")
    st.dataframe(
        top_total_picks[
            ["Matchup", "Model Total Runs", "Vegas Total", "Edge (Total)",
             "Model Pick (Total)", "Confidence (Total)"]
        ].reset_index(drop=True),
        use_container_width=True
    )
