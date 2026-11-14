# Cadence

CPR coaching on Even Realities G2 glasses with a wrist sensor.
**Training tool for manikin or pillow practice. Not a medical device. Never practice on a person.**

## Hub (Person 3)

Message format every component uses: [PROTOCOL.md](PROTOCOL.md).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                  # then put your OpenAI key in .env (git ignores it)
.venv/bin/python hub/hub.py           # prints the LAN address for the phone; dashboard at http://localhost:8000
.venv/bin/python hub/fake_sensor.py   # fake compression stream until the Vexo band is wired up
.venv/bin/python hub/test_hub.py      # self-check
```

- Person 1 (band): `POST /msg` with `compression` and `vitals` messages (format in PROTOCOL.md).
- Person 2 (glasses): open the app with `?ws=ws://<hub-ip>:8000` (the hub prints it). Same format as
  `glasses-app/src/protocol.ts`; the hub's IP must be in `app.json`'s network whitelist.
- UNO Q (anchor): `POST /msg` with `placement` messages.
