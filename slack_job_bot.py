"""
Job Posting Slack Bot
=====================
This bot monitors job postings for Product Manager roles in Finance, Healthcare, 
and Education sectors and sends them to a Slack channel.

Setup Instructions:
1. Create a Slack App at https://api.slack.com/apps
2. Add the following Bot Token Scopes:
   - chat:write
   - channels:read
   - chat:write.customize (optional, for custom bot name/icon)
3. Install the app to your workspace
4. Copy the Bot User OAuth Token (starts with xoxb-)
5. Add the bot to your desired channel
6. Set environment variable: SLACK_BOT_TOKEN
7. Install required packages: pip install slack-sdk requests beautifulsoup4 schedule
"""

import os
import requests
from datetime import datetime
from typing import List, Dict
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time
import json

class JobPostingBot:
    """Main bot class to handle job posting monitoring and Slack notifications"""

    def __init__(self, slack_token: str, channel_name: str, linkedin_cookie: str = None):
        """
        Initialize the bot with Slack credentials

        Args:
            slack_token: Slack Bot User OAuth Token (xoxb-...)
            channel_name: Channel name without # (e.g., 'job-alerts')
            linkedin_cookie: LinkedIn session cookie for accessing network posts (optional)
        """
        self.client = WebClient(token=slack_token)
        self.channel_name = channel_name
        self.channel_id = None
        self.posted_jobs = set()  # Track posted jobs to avoid duplicates
        self.linkedin_cookie = linkedin_cookie

        # Job search parameters
        self.target_roles = ["product manager", "senior product manager", 
                            "lead product manager", "principal product manager",
                            "product growth", "growth product manager"]
        self.target_industries = ["finance", "fintech", "healthcare", 
                                 "health tech", "education", "edtech"]
        self.target_locations = ["bangalore", "bengaluru", "pune", "chennai", 
                                "hyderabad", "remote", "hybrid", "work from home"]

    def get_channel_id(self) -> str:
        """
        Get channel ID from channel name

        Returns:
            str: Channel ID
        """
        try:
            # Call conversations.list API
            result = self.client.conversations_list()

            for channel in result.get('channels', []):
                if channel['name'] == self.channel_name:
                    self.channel_id = channel['id']
                    print(f"✓ Found channel #{self.channel_name} (ID: {self.channel_id})")
                    return self.channel_id

            raise Exception(f"Channel '{self.channel_name}' not found. "
                          f"Make sure the bot is added to the channel.")
        except SlackApiError as e:
            raise Exception(f"Error fetching channels: {e.response['error']}")

    def format_job_message(self, job: Dict) -> Dict:
        """
        Format job data into a rich Slack message block

        Args:
            job: Dictionary containing job details

        Returns:
            Dict: Formatted Slack message blocks
        """
        # Determine emoji based on job source/type
        emoji = "🎯"
        if job.get('is_network_post'):
            emoji = "👥"  # Network connection emoji
        elif "remote" in job.get('location', '').lower():
            emoji = "🌐"  # Remote work emoji

        # Create rich message blocks for better presentation
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {job['title']}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Company:*\n{job['company']}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Location:*\n{job['location']}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Industry:*\n{job.get('industry', 'N/A')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Posted:*\n{job.get('posted_date', 'Recently')}"
                    }
                ]
            }
        ]

        # Add network connection info if available
        if job.get('is_network_post') and job.get('posted_by'):
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"👤 Posted by: *{job['posted_by']}* ({job.get('connection_degree', 'Connection')})"
                    }
                ]
            })

        # Add description if available
        if job.get('description'):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Description:*\n{job['description'][:300]}..."
                }
            })

        # Add apply button
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": " "
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Apply Now 🚀" if not job.get('is_network_post') else "View Post 👀",
                    "emoji": True
                },
                "url": job['url'],
                "action_id": "apply_button"
            }
        })

        blocks.append({"type": "divider"})

        return blocks

    def send_job_to_slack(self, job: Dict) -> bool:
        """
        Send a job posting to the Slack channel

        Args:
            job: Dictionary containing job details

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create unique job identifier to prevent duplicates
            job_id = f"{job['company']}_{job['title']}_{job['location']}"

            if job_id in self.posted_jobs:
                print(f"⊘ Skipping duplicate: {job['title']} at {job['company']}")
                return False

            # Format the message
            blocks = self.format_job_message(job)

            # Send to Slack
            response = self.client.chat_postMessage(
                channel=self.channel_id,
                text=f"New Job: {job['title']} at {job['company']}",  # Fallback text
                blocks=blocks,
                unfurl_links=False
            )

            if response['ok']:
                self.posted_jobs.add(job_id)
                tag = "👥" if job.get('is_network_post') else "✓"
                print(f"{tag} Posted: {job['title']} at {job['company']}")
                return True
            else:
                print(f"✗ Failed to post: {response}")
                return False

        except SlackApiError as e:
            print(f"✗ Slack API Error: {e.response['error']}")
            return False

    def matches_location_filter(self, location: str) -> bool:
        """
        Check if a job location matches our target locations

        Args:
            location: Job location string

        Returns:
            bool: True if location matches, False otherwise
        """
        location_lower = location.lower()
        return any(target_loc in location_lower for target_loc in self.target_locations)

    def scrape_linkedin_network_posts(self) -> List[Dict]:
        """
        Scrape LinkedIn posts from your network about hiring for Product/Growth roles
        Note: This requires LinkedIn authentication

        Returns:
            List of job dictionaries from network posts
        """
        if not self.linkedin_cookie:
            print("⚠️  LinkedIn cookie not provided. Skipping network posts.")
            return []

        jobs = []

        # LinkedIn feed URL
        headers = {
            'Cookie': self.linkedin_cookie,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # Note: In production, you would:
        # 1. Use LinkedIn's official API if you have access
        # 2. Or use a service like PhantomBuster, Apify, or similar
        # 3. Respect LinkedIn's terms of service and rate limits

        # Example structure for network posts
        # In production, implement actual API calls or scraping
        sample_network_jobs = [
            {
                "title": "Product Manager - Growth",
                "company": "TechStartup India",
                "location": "Bangalore (Hybrid)",
                "industry": "Technology",
                "description": "We're hiring a PM to lead our growth initiatives. Looking for someone with 3+ years of experience in product-led growth.",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:example1",
                "posted_date": "1 day ago",
                "source": "LinkedIn Network",
                "is_network_post": True,
                "posted_by": "Rajesh Kumar",
                "connection_degree": "1st degree connection"
            },
            {
                "title": "Senior Product Manager",
                "company": "Innovation Labs",
                "location": "Pune (Remote)",
                "industry": "SaaS",
                "description": "Exciting opportunity to build the next generation of B2B products. Join our growing team!",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:example2",
                "posted_date": "3 hours ago",
                "source": "LinkedIn Network",
                "is_network_post": True,
                "posted_by": "Priya Sharma",
                "connection_degree": "2nd degree connection"
            }
        ]

        # Filter by location only (no industry filter for network posts)
        filtered_jobs = [
            job for job in sample_network_jobs 
            if self.matches_location_filter(job['location'])
        ]

        print(f"✓ Found {len(filtered_jobs)} network hiring posts (location-filtered)")
        return filtered_jobs

    def scrape_linkedin_jobs(self, keywords: str, location: str = "India") -> List[Dict]:
        """
        Scrape job postings from LinkedIn (via public search)

        Args:
            keywords: Job search keywords
            location: Location to search

        Returns:
            List of job dictionaries
        """
        jobs = []

        # Example job data structure (in production, implement actual scraping or use API)
        sample_jobs = [
            {
                "title": "Senior Product Manager - Healthcare",
                "company": "HealthTech Solutions India",
                "location": "Bangalore",
                "industry": "Healthcare",
                "description": "Looking for an experienced PM to lead our healthcare platform initiatives. Experience with telemedicine and healthcare workflows required.",
                "url": "https://www.linkedin.com/jobs/view/example1",
                "posted_date": "2 days ago",
                "source": "LinkedIn",
                "is_network_post": False
            },
            {
                "title": "Product Manager - Fintech",
                "company": "PayTech India",
                "location": "Pune (Hybrid)",
                "industry": "Finance",
                "description": "Join our team to build the next generation of payment products. Experience with UPI and digital payments preferred.",
                "url": "https://www.linkedin.com/jobs/view/example2",
                "posted_date": "1 day ago",
                "source": "LinkedIn",
                "is_network_post": False
            },
            {
                "title": "Lead Product Manager - EdTech",
                "company": "Learning Platform Co",
                "location": "Remote (India)",
                "industry": "Education",
                "description": "Lead the product strategy for our online learning platform serving millions of students across India.",
                "url": "https://www.linkedin.com/jobs/view/example3",
                "posted_date": "Today",
                "source": "LinkedIn",
                "is_network_post": False
            }
        ]

        # Filter by location
        filtered_jobs = [
            job for job in sample_jobs 
            if self.matches_location_filter(job['location'])
        ]

        return filtered_jobs

    def scrape_indeed_jobs(self, keywords: str, location: str = "India") -> List[Dict]:
        """
        Scrape job postings from Indeed

        Args:
            keywords: Job search keywords
            location: Location to search

        Returns:
            List of job dictionaries
        """
        jobs = []

        # Example job data
        sample_jobs = [
            {
                "title": "Product Manager - Digital Health",
                "company": "MedTech Innovations",
                "location": "Hyderabad",
                "industry": "Healthcare",
                "description": "Seeking a PM passionate about healthcare technology. Work on products that impact millions of patients across India.",
                "url": "https://www.indeed.com/viewjob?jk=example1",
                "posted_date": "Today",
                "source": "Indeed",
                "is_network_post": False
            },
            {
                "title": "Senior PM - Financial Services",
                "company": "Fintech Unicorn",
                "location": "Chennai (Remote)",
                "industry": "Finance",
                "description": "Build innovative financial products for the Indian market. Experience with lending, payments, or wealth management required.",
                "url": "https://www.indeed.com/viewjob?jk=example2",
                "posted_date": "2 days ago",
                "source": "Indeed",
                "is_network_post": False
            }
        ]

        # Filter by location
        filtered_jobs = [
            job for job in sample_jobs 
            if self.matches_location_filter(job['location'])
        ]

        return filtered_jobs

    def fetch_all_jobs(self) -> List[Dict]:
        """
        Fetch jobs from all sources

        Returns:
            List of all job postings
        """
        all_jobs = []

        print("\n🔍 Fetching jobs from multiple sources...")

        # 1. Fetch LinkedIn network posts (Product/Growth roles, location filter only)
        print("\n📱 Checking LinkedIn network posts...")
        network_jobs = self.scrape_linkedin_network_posts()
        all_jobs.extend(network_jobs)

        # 2. Fetch regular job postings (with industry filter)
        print("\n🔎 Searching job boards...")
        for role in self.target_roles:
            for industry in self.target_industries:
                for location in ["Bangalore", "Pune", "Chennai", "Hyderabad", "Remote India"]:
                    query = f"{role} {industry}"

                    # Fetch from LinkedIn
                    linkedin_jobs = self.scrape_linkedin_jobs(query, location)
                    all_jobs.extend(linkedin_jobs)

                    # Fetch from Indeed
                    indeed_jobs = self.scrape_indeed_jobs(query, location)
                    all_jobs.extend(indeed_jobs)

                    # Add delay to respect rate limits
                    time.sleep(2)

        # Remove duplicates based on title and company
        unique_jobs = []
        seen = set()

        for job in all_jobs:
            identifier = f"{job['title']}_{job['company']}"
            if identifier not in seen:
                seen.add(identifier)
                unique_jobs.append(job)

        network_count = sum(1 for job in unique_jobs if job.get('is_network_post'))
        regular_count = len(unique_jobs) - network_count

        print(f"\n✓ Found {len(unique_jobs)} unique job postings:")
        print(f"  - {network_count} from network connections")
        print(f"  - {regular_count} from job boards")

        return unique_jobs

    def run_once(self):
        """Run the bot once to fetch and post jobs"""
        print(f"\n{'='*60}")
        print(f"Job Posting Bot - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # Get channel ID if not already set
        if not self.channel_id:
            self.get_channel_id()

        # Fetch jobs
        jobs = self.fetch_all_jobs()

        # Post to Slack
        posted_count = 0
        for job in jobs:
            if self.send_job_to_slack(job):
                posted_count += 1
                time.sleep(1)  # Rate limiting

        print(f"\n📊 Summary: Posted {posted_count} new jobs to #{self.channel_name}")
        print(f"{'='*60}\n")

    def run_scheduled(self, interval_hours: int = 24):
        """
        Run the bot on a schedule

        Args:
            interval_hours: How often to check for new jobs (in hours)
        """
        print(f"🤖 Bot started! Checking for jobs every {interval_hours} hours...")
        print(f"📢 Posting to channel: #{self.channel_name}\n")

        while True:
            try:
                self.run_once()
                print(f"💤 Sleeping for {interval_hours} hours...\n")
                time.sleep(interval_hours * 3600)
            except KeyboardInterrupt:
                print("\n👋 Bot stopped by user")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                print(f"Retrying in 5 minutes...\n")
                time.sleep(300)


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_usage():
    """Example of how to use the bot"""

    # ========================================================================
    # 🔐 CONFIGURATION - UPDATE YOUR TOKENS HERE
    # ========================================================================

    # METHOD 1: Using environment variables (RECOMMENDED)
    slack_token = os.getenv('SLACK_BOT_TOKEN')
    linkedin_cookie = os.getenv('LINKEDIN_COOKIE')  # Optional

    # METHOD 2: Hard-coded (NOT recommended for production - use for testing only)
    # 📝 UPDATE THESE VALUES:
    # slack_token = 'xoxb-your-slack-bot-token-here'
    # linkedin_cookie = 'li_at=your-linkedin-cookie-here'  # Optional

    # ========================================================================

    if not slack_token:
        print("❌ Error: SLACK_BOT_TOKEN not set")
        print("\n🔐 To set your Slack Bot Token:")
        print("  Linux/Mac: export SLACK_BOT_TOKEN='xoxb-your-token-here'")
        print("  Windows: set SLACK_BOT_TOKEN=xoxb-your-token-here")
        print("\nOr update line 419-420 in this file with your token")
        return

    # Initialize bot
    # 📝 UPDATE THE CHANNEL NAME:
    bot = JobPostingBot(
        slack_token=xoxb-9951129876435-9961280660292-eVpGtBd37b6Mj7tMnppy45Oz,
        channel_name='job-notifications',  # ← UPDATE: Your channel name (without #)
        linkedin_cookie=linkedin_cookie  # Optional: for network posts
    )

    # Option 1: Run once (testing)
    print("Running bot once...")
    bot.run_once()

    # Option 2: Run on schedule (production)
    # Uncomment the lines below to run continuously:
    # print("Running bot on schedule...")
    # bot.run_scheduled(interval_hours=24)  # Check every 24 hours


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    example_usage()
