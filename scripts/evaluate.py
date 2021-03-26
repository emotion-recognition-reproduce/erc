from sklearn.metrics import f1_score
from tqdm import tqdm
import os
from glob import glob
import argparse
from fairseq.models.roberta import RobertaModel
from fairseq.data.data_utils import collate_tokens
import sys
import pprint
import json
import numpy as np
DATASET_DIR = "Datasets/"
MODEL_DIR = 'models/'
DATASETS_SUPPORTED = ['MELD', 'IEMOCAP', 'EmoryNLP', 'DailyDialog']


def add_markdown_sota(sota_values):
    markdown = str("| ")
    markdown += str(sota_values['model']) + " | "
    markdown += "SOTA" + " | "
    markdown += " " + " | "
    markdown += " " + " | "
    markdown += str(sota_values['value']) + " |"
    markdown += "\n"

    return markdown


def make_markdown_table(array):
    """ Input: Python list with rows of table as lists
               First element as header. 
        Output: String to put into a .md file 

    Ex Input: 
        [["Name", "Age", "Height"],
         ["Jake", 20, 5'10],
         ["Mary", 21, 5'7]] 
    """

    markdown = "\n" + "| "

    for e in array[0]:
        to_add = " " + str(e) + " |"
        markdown += to_add
    markdown += "\n"

    markdown += '|'
    for i in range(len(array[0])):
        markdown += "-------------- | "
    markdown += "\n"

    for entry in array[1:]:
        markdown += "| "
        for e in entry:
            to_add = str(e) + " | "
            markdown += to_add
        markdown += "\n"

    # if len(array) > 1:
    #     markdown += "| "
    #     for e in array[-1]:
    #         to_add = "**" + str(e) + "**" + " |"
    #         markdown += to_add
    #     markdown += "\n"

    return markdown


def evalute_SPLIT(roberta, DATASET, batch_size, SPLIT):

    def label_fn(label):
        return roberta.task.label_dictionary.string(
            [label + roberta.task.label_dictionary.nspecial])

    y_true = []
    y_pred = []

    X = {}
    num_inputs = len(glob(os.path.join(DATASET_DIR, DATASET, 'roberta',
                                       f"{SPLIT}.input*.bpe")))
    for i in range(num_inputs):
        X[i] = os.path.join(DATASET_DIR, DATASET,
                            'roberta', SPLIT + f'.input{i}')

        with open(X[i], 'r') as stream:
            X[i] = [line.strip() for line in stream.readlines()]

    Y = os.path.join(DATASET_DIR, DATASET, 'roberta', SPLIT + '.label')
    with open(Y, 'r') as stream:
        Y = [line.strip() for line in stream.readlines()]

    for i in range(num_inputs):
        assert len(X[i]) == len(Y)

    original_length = len(Y)
    num_batches = original_length // batch_size

    for i in range(num_inputs):
        X[i] = [X[i][j*batch_size:(j+1)*batch_size] for j in range(num_batches)] + \
            [[X[i][j]] for j in range(batch_size*num_batches, original_length)]

    Y = [Y[j*batch_size:(j+1)*batch_size] for j in range(num_batches)] + \
        [[Y[j]] for j in range(batch_size*num_batches, original_length)]

    for i in range(num_inputs):
        assert len(X[i]) == len(Y)

    for idx in tqdm(range(len(Y))):
        batch = [X[i][idx] for i in range(num_inputs)]
        batch = list(map(list, zip(*batch)))

        batch = collate_tokens(
            [roberta.encode(*[sequence for sequence in sequences])
             for sequences in batch], pad_idx=1
        )

        logprobs = roberta.predict(DATASET + '_head', batch)
        pred = logprobs.argmax(dim=1)
        label = Y[idx]

        assert len(pred) == len(label)
        for p, l in zip(pred, label):
            y_true.append(l)
            y_pred.append(label_fn(p))

    assert original_length == len(y_true) == len(y_pred), \
        f"{original_length}, {len(y_true)}, {len(y_pred)}"

    scores_all = {}
    scores_all['f1_weighted'] = f1_score(y_true, y_pred, average='weighted')
    scores_all['f1_micro'] = f1_score(y_true, y_pred, average='micro')
    scores_all['f1_macro'] = f1_score(y_true, y_pred, average='macro')

    return scores_all


def evaluate_model(DATASET, seed, checkpoint_dir, base_dir, metric,
                   batch_size, use_cuda, **kwargs):
    if DATASET not in DATASETS_SUPPORTED:
        sys.exit(f"{DATASET} is not supported!")

    if metric.lower() not in ['f1_weighted', 'f1_micro', 'f1_macro',
                              'cross_entropy_loss']:
        raise ValueError(f"{metric} not supported!!")

    if metric.lower() == 'cross_entropy_loss':
        model_paths = glob(os.path.join(checkpoint_dir, 'checkpoint_best.pt'))
    else:
        model_paths = glob(os.path.join(checkpoint_dir, '*.pt'))
        model_paths = [path for path in model_paths if os.path.basename(
            path) not in ['checkpoint_last.pt', 'checkpoint_best.pt']]

    stats = {}
    for model_path in tqdm(model_paths):
        checkpoint_file = os.path.basename(model_path)
        print(checkpoint_file)

        roberta = RobertaModel.from_pretrained(
            checkpoint_dir,
            checkpoint_file=checkpoint_file,
            data_name_or_path=os.path.join(DATASET_DIR, DATASET, 'roberta/bin')
        )

        roberta.eval()  # disable dropout
        if use_cuda:
            roberta.cuda()
        SPLIT = 'val'
        print(f"evaluating {DATASET}, {model_path}, {SPLIT} ...")
        scores = evalute_SPLIT(roberta, DATASET,
                               batch_size, SPLIT=SPLIT)
        print(model_path)
        pprint.PrettyPrinter(indent=4).pprint(scores)
        stats[model_path] = scores

        del roberta

    pprint.PrettyPrinter(indent=4).pprint(stats)

    if metric != 'cross_entropy_loss':
        stats = {key: val[metric] for key, val in stats.items()}

    if len(stats) > 1:
        best_model_path = max(stats, key=stats.get)
    else:
        best_model_path = list(stats.keys())[0]

    print(f"{best_model_path} has the best {metric} performance on val")

    checkpoint_file = os.path.basename(best_model_path)
    roberta = RobertaModel.from_pretrained(
        checkpoint_dir,
        checkpoint_file=checkpoint_file,
        data_name_or_path=os.path.join(DATASET_DIR, DATASET, 'roberta/bin')
    )

    roberta.eval()  # disable dropout
    if use_cuda:
        roberta.cuda()

    stats = {}
    for SPLIT in tqdm(['train', 'val', 'test']):
        print(f"evaluating {DATASET}, {best_model_path}, {SPLIT} ...")
        scores = evalute_SPLIT(roberta, DATASET,
                               batch_size, SPLIT=SPLIT)

        stats[SPLIT] = scores
    pprint.PrettyPrinter(indent=4).pprint(stats)

    del roberta

    with open(os.path.join(base_dir, f"{seed}.json"),  'w') as stream:
        json.dump(stats, stream, indent=4, ensure_ascii=False)

    for model_path in glob(os.path.join(checkpoint_dir, '*.pt')):
        os.remove(model_path)


def hasNumbers(inputString):
    return any(char.isdigit() for char in inputString)


def evaluate_all_seeds(base_dir):
    DIR_NAME = base_dir
    jsonpaths = [path for path in glob(os.path.join(DIR_NAME, '*.json'))
                 if hasNumbers(os.path.basename(path))]

    metrics = ['f1_weighted', 'f1_micro', 'f1_macro']
    scores_all = {SPLIT: {metric: [] for metric in metrics}
                  for SPLIT in ['train', 'val', 'test']}

    for jsonpath in jsonpaths:
        with open(jsonpath, 'r') as stream:
            scores = json.load(stream)

        for SPLIT in ['train', 'val', 'test']:
            for metric in metrics:
                if metric in scores[SPLIT].keys():
                    scores_all[SPLIT][metric].append(scores[SPLIT][metric])

    for SPLIT in ['train', 'val', 'test']:
        for metric in metrics:
            if metric in scores[SPLIT].keys():
                scores_all[SPLIT][metric] = {
                    'mean': np.mean(np.array(scores_all[SPLIT][metric])),
                    'std': np.std(np.array(scores_all[SPLIT][metric]))}

    pprint.PrettyPrinter(indent=4).pprint(scores_all)

    with open(os.path.join(DIR_NAME, 'results.json'), 'w') as stream:
        json.dump(scores_all, stream, indent=4, ensure_ascii=False)


def leaderboard():
    with open('scripts/sota.json', 'r') as stream:
        sota = json.load(stream)
    results_paths = glob(os.path.join(MODEL_DIR, '*/*/*/results.json'))
    print(results_paths)

    leaderboard = {DATASET: [] for DATASET in DATASETS_SUPPORTED}
    for path in results_paths:
        BASE_MODEL = path.split('/')[1]
        DATASET = path.split('/')[2]
        METHOD = path.split('/')[3]

        with open(path, 'r') as stream:
            results = json.load(stream)

        if DATASET == 'DailyDialog':
            metric = 'f1_micro'
        else:
            metric = 'f1_weighted'

        leaderboard[DATASET].append([BASE_MODEL, METHOD,
                                     round(results['train']
                                           [metric]['mean']*100, 3),
                                     round(results['val'][metric]
                                           ['mean']*100, 3),
                                     round(results['test'][metric]['mean']*100, 3)])

    with open('LEADERBOARD.md', 'w') as stream:
        stream.write('# Leaderboard\n')
        stream.write("Note that only DailyDialog uses a different metric "
                     "(f1_micro) from others (f1_weighted). f1_micro is the "
                     "same as accuracy when every data point is assigned only "
                     "one class.\n\nThe reported performance of my models are "
                     "the mean values of the 5 random seed runs. I expect the "
                     "other authors have done the same thing or something "
                     "similar, since the numbers are stochastic in nature.\n\n"
                     "Since the distribution of classes is different for every "
                     "dataset and train / val / tests splits, and also not all "
                     "datasets have the same performance metric, the optimization "
                     "is done to minimize the validation cross entropy loss, "
                     "since its the most generic metric, "
                     "with backpropagation on training data split.\n\n")

    for DATASET in DATASETS_SUPPORTED:

        if DATASET == 'DailyDialog':
            metric = 'f1_micro'
        else:
            metric = 'f1_weighted'

        leaderboard[DATASET].sort(key=lambda x: x[1])
        table = leaderboard[DATASET]
        table.insert(0, ["base model", "method", "train", "val", "test"])

        with open('LEADERBOARD.md', 'a') as stream:
            table = make_markdown_table(table)

            stream.write(f"## {DATASET} \n")
            stream.write(f"The metric is {metric} (%)")
            stream.write(table)
            table = add_markdown_sota(sota[DATASET])
            stream.write(table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='evaluate the model on f1 and acc')
    parser.add_argument('--DATASET', default=None,
                        help='e.g. IEMOCAP, MELD, EmoryNLP, DailyDialog')
    parser.add_argument('--seed', type=int, default=None, help='e.g. SEED num')
    parser.add_argument('--model-path', default=None, help='e.g. model path')
    parser.add_argument('--batch-size', default=1,
                        type=int, help='e.g. 1, 2, 4')
    parser.add_argument('--checkpoint-dir', default=None)
    parser.add_argument('--base-dir', default=None)
    parser.add_argument('--metric', default='f1_weighted')
    parser.add_argument('--use-cuda', action='store_true')
    parser.add_argument('--evaluate-seeds', action='store_true')
    parser.add_argument('--leaderboard', action='store_true')

    args = parser.parse_args()
    args = vars(args)
    print(f"arguments given to {__file__}: {args}")

    if args['evaluate_seeds']:
        evaluate_all_seeds(args['base_dir'])
    elif args['leaderboard']:
        leaderboard()
    else:
        evaluate_model(**args)
