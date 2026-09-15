from apscheduler.schedulers.blocking import BlockingScheduler
from app import pull_outlook

scheduler=BlockingScheduler(timezone='Europe/London')
scheduler.add_job(pull_outlook,'cron',hour=19,minute=0,id='outlook_daily',max_instances=1,coalesce=True)
scheduler.start()
