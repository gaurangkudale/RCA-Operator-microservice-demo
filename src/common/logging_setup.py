import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging(service_name):
    """Setup basic JSON logging with JSON formatter."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    class CustomJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            log_record["Severity"] = record.levelname
            log_record["Message"] = record.getMessage()
            log_record["Service"] = service_name

            if record.exc_info:
                log_record["Exception"] = record.exc_info[0].__name__

    log_handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "Timestamp", "levelname": "level"},
    )
    log_handler.setFormatter(formatter)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.addHandler(log_handler)

    # Configure uvicorn loggers
    logging.getLogger("uvicorn.access").handlers = [log_handler]
    logging.getLogger("uvicorn.error").handlers = [log_handler]

    return logging.getLogger(service_name)
