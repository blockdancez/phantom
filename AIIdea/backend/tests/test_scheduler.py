from src.scheduler.jobs import create_scheduler


def test_scheduler_has_three_jobs():
    scheduler = create_scheduler()
    jobs = scheduler.get_jobs()
    job_ids = [j.id for j in jobs]

    assert "collect_data" in job_ids
    assert "process_data" in job_ids
    assert "analyze_data" in job_ids
