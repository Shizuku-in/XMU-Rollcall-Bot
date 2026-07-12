## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py config   # configure your account. support multiple accounts.
python main.py switch   # switch between accounts.
python main.py start    # start the monitor.
python main.py start --at 08:00  # start at the next local 08:00 and keep retrying on failure.
python main.py refresh  # refresh the login status.
```

`start --at HH:MM` keeps the process running until the next matching local time.
After a login or monitoring failure, it retries automatically with exponential
backoff (10 seconds, 20 seconds, 40 seconds, up to 5 minutes). Keep the
computer awake and the terminal process running until the scheduled time.
