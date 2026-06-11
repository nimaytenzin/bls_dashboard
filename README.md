# bls_dashboard

BLS 26 liveability heatmap dashboard for Bhutan.

## Contents

- `heatmap.html` — Interactive heatmap visualization
- `data/` — Liveability heatmap data and legend
- `assets/` — GeoJSON boundaries (Thimphu, Mongar, Samdrup Jongkhar, Phuentsholing)
- `scripts/` — Build scripts for generating heatmap data

## Usage

Open `heatmap.html` in a browser, or run a local server:

```bash
python3 -m http.server 8000
```

Then visit http://localhost:8000/heatmap.html
