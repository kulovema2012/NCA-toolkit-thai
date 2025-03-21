"""
Queue processor for high-volume video captioning tasks.
This module implements an asynchronous job queue for processing video captioning requests.
"""

import os
import time
import uuid
import json
import logging
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from concurrent.futures import ThreadPoolExecutor
import traceback

# Import the captioning module
from services.v1.video.caption_video import add_subtitles_to_video, process_captioning_v1

# Configure logging
logger = logging.getLogger(__name__)

# Job status constants
JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_RETRY = "retry"

# Queue configuration
MAX_WORKERS = 4  # Maximum number of concurrent workers
MAX_QUEUE_SIZE = 100  # Maximum number of jobs in the queue
MAX_RETRIES = 3  # Maximum number of retries for failed jobs
JOB_TIMEOUT = timedelta(minutes=30)  # Maximum time a job can run

# Job priority levels
PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_LOW = 2

# Job queues (priority-based)
job_queues = {
    PRIORITY_HIGH: queue.PriorityQueue(),
    PRIORITY_NORMAL: queue.PriorityQueue(),
    PRIORITY_LOW: queue.PriorityQueue()
}

# Job status tracking
job_status = {}  # {job_id: {status, result, start_time, end_time, retries, error}}
job_status_lock = threading.Lock()

# Worker pool
worker_pool = None

# Shutdown flag
shutdown_flag = threading.Event()


class CaptioningJob:
    """Represents a video captioning job in the queue."""
    
    def __init__(self, job_id: str, params: Dict[str, Any], priority: int = PRIORITY_NORMAL):
        """
        Initialize a captioning job.
        
        Parameters:
        -----------
        job_id : str
            Unique identifier for the job
        params : Dict[str, Any]
            Parameters for the captioning process
        priority : int, default=PRIORITY_NORMAL
            Job priority (0=high, 1=normal, 2=low)
        """
        self.job_id = job_id
        self.params = params
        self.priority = priority
        self.sequence = int(time.time() * 1000)  # Used for FIFO ordering within same priority
        
    def __lt__(self, other):
        """Compare jobs for priority queue ordering."""
        if self.priority == other.priority:
            return self.sequence < other.sequence
        return self.priority < other.priority


def initialize_queue_processor():
    """Initialize the queue processor and start worker threads."""
    global worker_pool
    
    if worker_pool is not None:
        logger.warning("Queue processor already initialized")
        return
    
    logger.info(f"Initializing queue processor with {MAX_WORKERS} workers")
    worker_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    
    # Start worker threads
    for _ in range(MAX_WORKERS):
        worker_pool.submit(worker_thread)
    
    # Start monitoring thread
    threading.Thread(target=monitor_thread, daemon=True).start()
    
    logger.info("Queue processor initialized successfully")


def shutdown_queue_processor():
    """Shutdown the queue processor gracefully."""
    global worker_pool
    
    if worker_pool is None:
        logger.warning("Queue processor not initialized")
        return
    
    logger.info("Shutting down queue processor")
    shutdown_flag.set()
    
    # Wait for worker pool to complete
    worker_pool.shutdown(wait=True)
    worker_pool = None
    
    logger.info("Queue processor shutdown complete")


def enqueue_job(params: Dict[str, Any], job_id: Optional[str] = None, 
                priority: int = PRIORITY_NORMAL) -> str:
    """
    Add a captioning job to the queue.
    
    Parameters:
    -----------
    params : Dict[str, Any]
        Parameters for the captioning process
    job_id : str, optional
        Unique identifier for the job (generated if not provided)
    priority : int, default=PRIORITY_NORMAL
        Job priority (0=high, 1=normal, 2=low)
    
    Returns:
    --------
    str
        Job ID for tracking the job status
    
    Raises:
    -------
    ValueError
        If the queue is full or parameters are invalid
    """
    # Validate parameters
    if not params.get('video_url') and not params.get('video_path'):
        raise ValueError("Missing video URL or path")
    
    if not params.get('subtitle_file') and not params.get('subtitle_path'):
        raise ValueError("Missing subtitle file or path")
    
    # Check queue size
    if sum(q.qsize() for q in job_queues.values()) >= MAX_QUEUE_SIZE:
        raise ValueError("Queue is full, try again later")
    
    # Generate job ID if not provided
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    # Create job object
    job = CaptioningJob(job_id, params, priority)
    
    # Update job status
    with job_status_lock:
        job_status[job_id] = {
            'status': JOB_STATUS_PENDING,
            'created_at': datetime.now(),
            'priority': priority,
            'retries': 0,
            'params': params
        }
    
    # Add to appropriate queue
    job_queues[priority].put(job)
    logger.info(f"Job {job_id} added to queue with priority {priority}")
    
    return job_id


def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get the status of a job.
    
    Parameters:
    -----------
    job_id : str
        Job ID to check
    
    Returns:
    --------
    Dict[str, Any]
        Job status information
    
    Raises:
    -------
    ValueError
        If the job ID is not found
    """
    with job_status_lock:
        if job_id not in job_status:
            raise ValueError(f"Job ID {job_id} not found")
        
        # Return a copy to avoid race conditions
        return dict(job_status[job_id])


def cancel_job(job_id: str) -> bool:
    """
    Cancel a pending job.
    
    Parameters:
    -----------
    job_id : str
        Job ID to cancel
    
    Returns:
    --------
    bool
        True if the job was cancelled, False if it was already processing
    
    Raises:
    -------
    ValueError
        If the job ID is not found
    """
    with job_status_lock:
        if job_id not in job_status:
            raise ValueError(f"Job ID {job_id} not found")
        
        status = job_status[job_id]['status']
        
        if status == JOB_STATUS_PENDING:
            job_status[job_id]['status'] = JOB_STATUS_FAILED
            job_status[job_id]['error'] = "Job cancelled by user"
            job_status[job_id]['end_time'] = datetime.now()
            logger.info(f"Job {job_id} cancelled")
            return True
        
        logger.warning(f"Cannot cancel job {job_id} with status {status}")
        return False


def worker_thread():
    """Worker thread function to process jobs from the queue."""
    logger.info("Worker thread started")
    
    while not shutdown_flag.is_set():
        job = None
        
        # Try to get a job from the queues in priority order
        for priority in sorted(job_queues.keys()):
            try:
                job = job_queues[priority].get(block=False)
                break
            except queue.Empty:
                continue
        
        if job is None:
            # No jobs in any queue, wait a bit
            time.sleep(0.5)
            continue
        
        # Process the job
        process_job(job)
        
        # Mark the job as done in the queue
        job_queues[job.priority].task_done()
    
    logger.info("Worker thread stopped")


def process_job(job: CaptioningJob):
    """
    Process a captioning job.
    
    Parameters:
    -----------
    job : CaptioningJob
        Job to process
    """
    job_id = job.job_id
    params = job.params
    
    # Update job status to processing
    with job_status_lock:
        if job_id not in job_status:
            logger.error(f"Job {job_id} not found in status tracking")
            return
        
        if job_status[job_id]['status'] != JOB_STATUS_PENDING:
            logger.warning(f"Job {job_id} is not in pending status, skipping")
            return
        
        job_status[job_id]['status'] = JOB_STATUS_PROCESSING
        job_status[job_id]['start_time'] = datetime.now()
    
    logger.info(f"Processing job {job_id}")
    
    try:
        # Call the captioning process
        result = process_captioning_v1(params)
        
        # Update job status to completed
        with job_status_lock:
            job_status[job_id]['status'] = JOB_STATUS_COMPLETED
            job_status[job_id]['result'] = result
            job_status[job_id]['end_time'] = datetime.now()
        
        logger.info(f"Job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Update job status to failed or retry
        with job_status_lock:
            retries = job_status[job_id].get('retries', 0)
            
            if retries < MAX_RETRIES:
                # Schedule for retry
                job_status[job_id]['status'] = JOB_STATUS_RETRY
                job_status[job_id]['retries'] = retries + 1
                job_status[job_id]['error'] = str(e)
                
                # Re-queue the job with a delay based on retry count
                retry_job = CaptioningJob(job_id, params, job.priority)
                retry_job.sequence = int(time.time() * 1000) + (retries * 60000)  # Add delay
                job_queues[job.priority].put(retry_job)
                
                logger.info(f"Job {job_id} scheduled for retry {retries + 1}/{MAX_RETRIES}")
            else:
                # Max retries reached, mark as failed
                job_status[job_id]['status'] = JOB_STATUS_FAILED
                job_status[job_id]['error'] = str(e)
                job_status[job_id]['end_time'] = datetime.now()
                
                logger.warning(f"Job {job_id} failed after {MAX_RETRIES} retries")


def monitor_thread():
    """Monitor thread to check for stalled jobs and clean up old job statuses."""
    logger.info("Monitor thread started")
    
    while not shutdown_flag.is_set():
        now = datetime.now()
        
        with job_status_lock:
            # Check for stalled jobs
            for job_id, status in list(job_status.items()):
                if status['status'] == JOB_STATUS_PROCESSING:
                    start_time = status.get('start_time')
                    if start_time and (now - start_time) > JOB_TIMEOUT:
                        logger.warning(f"Job {job_id} has exceeded timeout, marking as failed")
                        status['status'] = JOB_STATUS_FAILED
                        status['error'] = "Job exceeded maximum execution time"
                        status['end_time'] = now
                
                # Clean up old completed/failed jobs (keep for 24 hours)
                if status['status'] in (JOB_STATUS_COMPLETED, JOB_STATUS_FAILED):
                    end_time = status.get('end_time')
                    if end_time and (now - end_time) > timedelta(hours=24):
                        logger.info(f"Removing old job {job_id} from status tracking")
                        job_status.pop(job_id, None)
        
        # Sleep for a while
        time.sleep(60)  # Check every minute
    
    logger.info("Monitor thread stopped")


def get_queue_stats() -> Dict[str, Any]:
    """
    Get statistics about the job queues.
    
    Returns:
    --------
    Dict[str, Any]
        Queue statistics
    """
    with job_status_lock:
        total_jobs = len(job_status)
        pending_jobs = sum(1 for s in job_status.values() if s['status'] == JOB_STATUS_PENDING)
        processing_jobs = sum(1 for s in job_status.values() if s['status'] == JOB_STATUS_PROCESSING)
        completed_jobs = sum(1 for s in job_status.values() if s['status'] == JOB_STATUS_COMPLETED)
        failed_jobs = sum(1 for s in job_status.values() if s['status'] == JOB_STATUS_FAILED)
        retry_jobs = sum(1 for s in job_status.values() if s['status'] == JOB_STATUS_RETRY)
    
    return {
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'processing_jobs': processing_jobs,
        'completed_jobs': completed_jobs,
        'failed_jobs': failed_jobs,
        'retry_jobs': retry_jobs,
        'queue_sizes': {
            'high': job_queues[PRIORITY_HIGH].qsize(),
            'normal': job_queues[PRIORITY_NORMAL].qsize(),
            'low': job_queues[PRIORITY_LOW].qsize()
        },
        'max_workers': MAX_WORKERS,
        'max_queue_size': MAX_QUEUE_SIZE,
        'max_retries': MAX_RETRIES
    }


# Initialize the queue processor on module import
if __name__ != "__main__":
    initialize_queue_processor()
