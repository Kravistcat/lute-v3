"""
Tasks to run using Invoke.

Ref https://docs.pyinvoke.org/en/stable/index.html

Samples:

invoke lint
invoke coverage --html

invoke --list          # list all tasks
invoke --help <cmd>    # See docstrings and help notes
"""

import os
import subprocess
from datetime import datetime
import requests
from invoke import task, Collection
from lute.config.app_config import AppConfig


@task
def lint(c):
    "Run pylint on lute/ and tests/."
    # Formats: https://pylint.pycqa.org/en/latest/user_guide/usage/output.html
    msgfmt = "--msg-template='{path} ({line:03d}): {msg} ({msg_id} {symbol})'"
    c.run(f"pylint {msgfmt} tasks.py lute/ tests/")


@task(help={"html": "open html report"})
def coverage(c, html=False):
    """
    Run coverage, open report if needed.
    """
    c.run("coverage run -m pytest tests/")
    if html:
        c.run('coverage html --omit="*/test*"')
        c.run("open htmlcov/index.html")
    else:
        c.run('coverage report --omit="*/test*"')


@task
def todos(c):
    """
    Print code TODOs.
    """
    c.run("python utils/todos.py")


@task
def start(c):
    """
    Start the dev server, using script dev.py.
    """
    c.run("python -m devstart")


@task
def resetstart(c):
    "Reset the db, and start the app."
    db_reset(c)
    start(c)


@task
def search(c, search_for):
    """
    Search the code for a string.
    """
    thisdir = os.path.dirname(os.path.realpath(__file__))
    devscript = os.path.join(thisdir, "utils", "findstring.sh")
    c.run(f'{devscript} "{search_for}"')


@task
def test(c):
    """
    Simple caller to pytest to allow for inv task chaining.
    """
    c.run("pytest")


@task(
    help={
        "port": "optional port to run on; creates server if needed.",
        "show": "print data",
        "headless": "run as headless",
        "kflag": "optional -k flag argument",
        "exitfirst": "exit on first failure",
    }
)
def accept(  # pylint: disable=too-many-arguments
    c, port=None, show=False, headless=False, kflag=None, exitfirst=False
):
    """
    Start lute on 9876, run tests/acceptance tests, screenshot fails.

    If no port specified, use the port in the app config.

    If port is specified, and Lute's not running on that port,
    start a server.
    """
    ac = AppConfig.create_from_config()
    if ac.is_test_db is False:
        raise ValueError("not a test db")

    useport = port
    if useport is None:
        useport = ac.port

    url = f"http://localhost:{useport}"
    site_running = False
    try:
        print(f"checking for site at {url} ...")
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            raise RuntimeError(f"Got code {resp.status_code} ... ???")
        print("Site running, using that for tests.")
        print()
        site_running = True
    except requests.exceptions.ConnectionError:
        print(f"URL {url} not reachable, will start new server at that port.")
        print()

    run_test = [
        "pytest",
        "tests/acceptance",
        "--splinter-screenshot-dir=tests/acceptance/failure_screenshots",
        "--splinter-webdriver=chrome",
        f"--port={useport}",
    ]

    if show:
        run_test.append("-s")
    if headless:
        run_test.append("--headless")
    if kflag:
        run_test.append("-k")
        run_test.append(kflag)
    if exitfirst:
        run_test.append("--exitfirst")

    if site_running:
        c.run(" ".join(run_test))
    else:
        cmd = ["python", "-m", "tests.acceptance.start_acceptance_app", f"{useport}"]
        with subprocess.Popen(cmd) as app_process:
            subprocess.run(run_test, check=True)
            app_process.terminate()


@task(pre=[test, accept, lint])
def full(c):  # pylint: disable=unused-argument
    """
    Run full check and lint.
    """
    print("Done.")


@task(post=[lint])
def black(c):
    "black-format lute and tests, then check."
    c.run("python -m black lute")
    c.run("python -m black tests")


ns = Collection()
ns.add_task(full)
ns.add_task(lint)
ns.add_task(test)
ns.add_task(accept)
ns.add_task(coverage)
ns.add_task(todos)
ns.add_task(start)
ns.add_task(resetstart)
ns.add_task(search)
ns.add_task(black)


##############################
# DB tasks


def _ensure_test_db():
    "Throw if not a testing db."
    ac = AppConfig.create_from_config()
    if ac.is_test_db is False:
        raise ValueError("not a test db")


@task
def db_wipe(c):
    """
    Wipe the data from the testing db; factory reset settings. :-)

    Can only be run on a testing db.
    """
    _ensure_test_db()
    c.run("pytest -m dbwipe")
    print("ok")


@task
def db_reset(c):
    """
    Reset the database to the demo data.

    Can only be run on a testing db.
    """
    _ensure_test_db()
    c.run("pytest -m dbdemoload")
    print("ok")


def _schema_dir():
    "Return full path to schema dir."
    thisdir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(thisdir, "lute", "db", "schema")


def _do_schema_export(c, destfile, header_notes, taskname):
    """
    Generate the dumpfile at destfile.
    """
    destfile = os.path.join(_schema_dir(), destfile)
    tempfile = f"{destfile}.temp"
    commands = f"""
    echo "-- ------------------------------------------" > {tempfile}
    echo "-- {header_notes}" >> {tempfile}
    echo "-- Migrations tracked in _migrations, settings reset." >> {tempfile}
    echo "-- Generated from 'inv {taskname}'" >> {tempfile}
    echo "-- ------------------------------------------" >> {tempfile}
    echo "" >> {tempfile}
    sqlite3 data/test_lute.db .dump >> {tempfile}
    """
    c.run(commands)

    os.rename(tempfile, destfile)
    print(f"{destfile} updated (git diff follows):")
    print("DIFF START " + "-" * 38)
    c.run(f"git diff -- {destfile}")
    print("DIFF END " + "-" * 40)
    print()


@task
def db_export_baseline(c):
    """
    Reset the db, and create a new baseline db file from the current db.
    """

    # Running the delete task before this one as a pre- step was
    # causing problems (sqlite file not in correct state), so this
    # asks the user to verify.
    text = input("Have you reset the db?  (y/n): ")
    if text != "y":
        print("quitting.")
        return
    _do_schema_export(
        c, "baseline.sql", "Baseline db with demo data.", "db.export.baseline"
    )

    fname = os.path.join(_schema_dir(), "baseline.sql")
    print(f"Verifying {fname}")
    with open(fname, "r", encoding="utf-8") as f:
        checkstring = "Tutorial follow-up"
        if checkstring in f.read():
            print(f'"{checkstring}" found, likely ok.')
        else:
            print(f'"{checkstring}" NOT FOUND, SOMETHING LIKELY WRONG.')
            raise RuntimeError(f'Missing "{checkstring}" in exported file.')


@task
def db_export_empty(c):
    """
    Create a new empty db file from the current db.

    This assumes that the current db is in data/test_lute.db.
    """

    # Running the delete task before this one as a pre- step was
    # causing problems (sqlite file not in correct state), so this
    # asks the user to verify.
    text = input("Have you **WIPED** the db?  (y/n): ")
    if text != "y":
        print("quitting.")
        return
    _do_schema_export(c, "empty.sql", "EMPTY DB.", "db.export.empty")


@task(help={"suffix": "suffix to add to filename."})
def db_newscript(c, suffix):  # pylint: disable=unused-argument
    """
    Create a new migration, <datetime>_suffix.sql
    """
    now = datetime.now()
    fnow = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{fnow}_{suffix}.sql"
    destfile = os.path.join(_schema_dir(), "migrations", filename)
    with open(destfile, "w", encoding="utf-8") as f:
        f.write("-- TODO - fill this in.")
    print("migration created:")
    print(destfile)


dbtasks = Collection("db")
dbtasks.add_task(db_reset, "reset")
dbtasks.add_task(db_wipe, "wipe")
dbtasks.add_task(db_newscript, "newscript")
dbexport = Collection("export")
dbexport.add_task(db_export_baseline, "baseline")
dbexport.add_task(db_export_empty, "empty")
dbtasks.add_collection(dbexport)

ns.add_collection(dbtasks)
