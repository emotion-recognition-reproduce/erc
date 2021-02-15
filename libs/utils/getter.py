from torch.utils.data import DataLoader

from losses import *
from datasets import *
from models import *
from metrics import *
from optimizers import *
from dataloaders import *
from schedulers import *


def get_instance(config, **kwargs):
    assert "name" in config
    config.setdefault("args", {})
    if config["args"] is None:
        config["args"] = {}
    return globals()[config["name"]](**config["args"], **kwargs)