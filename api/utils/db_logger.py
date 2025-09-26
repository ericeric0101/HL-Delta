import os
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

class SupabaseLogger:
    """
    A class to handle logging trade data to a Supabase database.
    """
    def __init__(self):
        """
        Initializes the Supabase client.
        It expects SUPABASE_URL and SUPABASE_KEY to be set as environment variables.
        """
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.client: Client = None

        if not self.supabase_url or not self.supabase_key:
            logger.warning("SUPABASE_URL and SUPABASE_KEY environment variables are not set. Trade logging to Supabase will be disabled.")
        else:
            try:
                self.client = create_client(self.supabase_url, self.supabase_key)
                logger.info("Successfully connected to Supabase for trade logging.")
            except Exception as e:
                logger.error(f"Failed to connect to Supabase: {e}")
                self.client = None

    def log_trade(self, trade_data: dict):
        """
        Logs a single trade record to the 'trade_logs' table in Supabase.

        Args:
            trade_data (dict): A dictionary containing the trade details.
                               e.g., {'timestamp': '...', 'coin': '...', ...}
        """
        if not self.client:
            # Log to debug if you want to see the data that would have been sent
            logger.debug(f"Supabase client not initialized. Skipping log for: {trade_data}")
            return

        try:
            # The table name is assumed to be 'trade_logs'
            data, count = self.client.table('trade_logs').insert(trade_data).execute()
            # Check for errors in the response
            if data and len(data) > 1 and data[1]:
                 logger.info(f"Successfully logged trade to Supabase for order_id: {trade_data.get('order_id')}")
            else:
                 logger.error(f"Failed to log trade to Supabase. Response: {data}")

        except Exception as e:
            logger.error(f"An exception occurred while logging trade to Supabase: {e}")

    def log_account_snapshot(self, snapshot_data: dict):
        """
        Logs a single account snapshot record to the 'account_snapshots' table in Supabase.

        Args:
            snapshot_data (dict): A dictionary containing the account snapshot details.
        """
        if not self.client:
            logger.debug(f"Supabase client not initialized. Skipping account snapshot log.")
            return

        payload = {k: v for k, v in snapshot_data.items() if v is not None}
        if "account_value" not in payload:
            # Nothing meaningful to store if總值都沒有，直接略過
            logger.warning(
                f"Skipping account snapshot log because 'account_value' is missing. Payload: {snapshot_data}"
            )
            return

        try:
            # The table name is assumed to be 'account_snapshots'
            data, count = self.client.table('account_snapshots').insert(payload).execute()
            if data and len(data) > 1 and data[1]:
                logger.info(f"Successfully logged account snapshot to Supabase at {snapshot_data.get('timestamp')}")
            else:
                logger.error(f"Failed to log account snapshot to Supabase. Response: {data}")
        except Exception as e:
            message = str(e)
            if "Could not find the" in message and "column" in message:
                # Supabase schema缺少某些欄位，移除後重試一次
                logger.warning(f"Account snapshot columns mismatch ({message}). Retrying with reduced payload.")
                reduced_payload = \
                    {key: value for key, value in payload.items() if key not in message and key != 'perp_account_value'}
                if "account_value" not in reduced_payload:
                    logger.warning(
                        f"Reduced payload after removing unsupported columns lacks 'account_value'. Skipping insert. Payload: {snapshot_data}"
                    )
                    return
                try:
                    if reduced_payload:
                        data, count = self.client.table('account_snapshots').insert(reduced_payload).execute()
                        if data and len(data) > 1 and data[1]:
                            logger.info(
                                f"Logged account snapshot with reduced payload at {snapshot_data.get('timestamp')}"
                            )
                        else:
                            logger.error(f"Failed to log reduced account snapshot to Supabase. Response: {data}")
                    else:
                        logger.error("Reduced account snapshot payload is empty, skipping insert.")
                except Exception as inner:
                    logger.error(
                        f"Retrying account snapshot insert failed: {inner}. Original payload: {snapshot_data}",
                        exc_info=True,
                    )
            else:
                logger.error(f"An exception occurred while logging account snapshot to Supabase: {e}")

# Create a singleton instance to be used across the application
db_logger = SupabaseLogger()
