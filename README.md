# Cadence

CPR coaching on Even Realities G2 glasses with a wrist sensor.
**Training tool for manikin or pillow practice. Not a medical device. Never practice on a person.**

## Parts

- [sensing/](sensing/README.md): wrist band → live compression messages (Person 1)
- [glasses-app/](glasses-app/README.md): the G2 glasses app, voice controlled (Person 2)
- [hub/](hub/): the hub that joins them, dashboard, voice-note timeline, UNO Q anchor (Person 3)
- [PROTOCOL.md](PROTOCOL.md): the message format every part uses

## Hub (Person 3)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                  # then put your OpenAI key in .env (git ignores it)
.venv/bin/python hub/hub.py           # prints the LAN address for the glasses; dashboard at http://localhost:8000
.venv/bin/python hub/fake_sensor.py   # fake band + anchor until the real ones are wired up
.venv/bin/python hub/test_hub.py      # self-check
```

- Person 1 (band): `python -m sensing.run 27 --post http://<hub-ip>:8000/msg --post-all`
- Person 2 (glasses): open the app with `?ws=ws://<hub-ip>:8000` (the hub prints it). The hub's
  address must be in `glasses-app/app.json`'s network whitelist.
- UNO Q (anchor): `hub/anchor.py` posts `placement` messages.
