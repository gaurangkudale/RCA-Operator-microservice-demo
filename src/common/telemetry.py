import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_telemetry(service_name):
    """Setup basic JSON logging with JSON formatter."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    class CustomJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            log_record['Severity'] = record.levelname
            log_record['Message'] = record.getMessage()
            log_record['Service'] = service_name
            
            if record.exc_info:
                log_record['Exception'] = record.exc_info[0].__name__

    logHandler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s', rename_fields={"asctime": "Timestamp", "levelname": "level"})
    logHandler.setFormatter(formatter)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.addHandler(logHandler)

    # Configure uvicorn loggers
    logging.getLogger("uvicorn.access").handlers = [logHandler]
    logging.getLogger("uvicorn.error").handlers = [logHandler]

    return logging.getLogger(service_name)
