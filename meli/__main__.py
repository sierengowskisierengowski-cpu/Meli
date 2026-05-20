"""
Meli entry point — handles both GUI launch and daemon modes.
Run as: python -m meli [--daemon ingest]
"""
import sys
import click
from meli import __version__


@click.command()
@click.version_option(__version__, prog_name="meli")
@click.option("--daemon", type=click.Choice(["ingest"]), default=None,
              help="Run a background daemon instead of the GUI")
@click.option("--debug", is_flag=True, default=False,
              help="Enable debug logging")
@click.option("--reset-auth", is_flag=True, default=False,
              help="Reset authentication (emergency recovery)")
def main(daemon: str | None, debug: bool, reset_auth: bool) -> None:
    """Meli — Honeypot Command Center"""
    import structlog
    from meli.utils.logger import setup_logging
    setup_logging(debug=debug)
    log = structlog.get_logger()

    if reset_auth:
        from meli.auth import reset_auth as do_reset
        do_reset()
        click.echo("Authentication reset. Launch Meli normally to set a new master password.")
        sys.exit(0)

    if daemon == "ingest":
        log.info("Starting Meli ingest daemon", version=__version__)
        from meli.ingest.daemon import IngestDaemon
        d = IngestDaemon()
        d.run()
        return

    # GUI launch
    log.info("Starting Meli GUI", version=__version__)
    from meli.app import MeliApplication
    app = MeliApplication()
    sys.exit(app.run(sys.argv[:1]))


if __name__ == "__main__":
    main()
