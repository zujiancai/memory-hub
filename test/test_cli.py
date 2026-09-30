def test_cli_cleanup_and_seed(app, client, upload_asset, signup_user, db_session):
    """Exercise cleanup + seed-dev-user CLI wiring."""
    from click.testing import CliRunner

    from server.cli import cleanup_command, seed_dev_user_command
    from server.models import User

    runner = CliRunner()
    with app.app_context():
        result = runner.invoke(seed_dev_user_command, ["--email", "seeded@ex.com"])
        assert result.exit_code == 0

    user = db_session.query(User).filter(User.email == "seeded@ex.com").first()
    assert user is not None

    with app.app_context():
        result = runner.invoke(cleanup_command)
        assert result.exit_code == 0
