import argparse
import numpy as np
from pathlib import Path
from covid19.datasets import image_dataset_from_directory
from covid19.metrics import plot_learning_curves
from covid19.models import ResNet50
from tensorflow.keras.losses import CategoricalCrossentropy
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping, TensorBoard
from tensorflow.keras.metrics import CategoricalAccuracy, AUC, Precision, Recall
from tensorflow_addons.metrics import F1Score

# training settings
LR = 0.0001
LR_FT = LR / 10             # learning rate for fine-tuning
EPOCHS = 20
EPOCHS_FT = 10              # epochs for fine-tuning
FINE_TUNE_AT = 150          # layer at which to start fine-tuning (layers [0, fine_tune_at-1] are frozen)

IMAGE_SIZE = (224, 224)
INPUT_SHAPE = IMAGE_SIZE + (3,)
VERBOSE = 2


def get_loss():
    return CategoricalCrossentropy()


def get_metrics(n_classes, covid19_label):
    # remarks:
    # - AUC and F1-score are computed with macro-average (we care a lot about the small COVID-19 class!)
    # - precision and recall are computed only on the COVID-19 class (again, it is the most important)
    return [
        CategoricalAccuracy(name='accuracy'),
        AUC(name='auc', multi_label=True),  # multi_label=True => macro-average
        F1Score(name='f1-score', num_classes=n_classes, average='macro'),
        Precision(name='precision_covid19', class_id=covid19_label),
        Recall(name='recall_covid19', class_id=covid19_label),
    ]


def get_callbacks(checkpoints_path, logs_path):
    filepath_checkpoint = checkpoints_path / '{epoch:02d}.h5'
    return [
        ModelCheckpoint(filepath=str(filepath_checkpoint), save_weights_only=True, verbose=VERBOSE),
        EarlyStopping(monitor='loss', mode='min', patience=5, restore_best_weights=True, verbose=VERBOSE),
        TensorBoard(log_dir=logs_path, profile_batch=0)
    ]


def get_class_weights(train_ds):
    total = train_ds.classes.shape[0]
    n_classes = len(train_ds.class_indices)
    class_weights = {}

    for class_name, class_label in train_ds.class_indices.items():
        # scale weights by total / n_classes to keep the loss to a similar magnitude
        # see https://www.tensorflow.org/tutorials/structured_data/imbalanced_data#class_weights
        n = len(np.where(train_ds.classes == class_label)[0])
        class_weights[class_label] = (1 / n) * (total / n_classes)
    return class_weights


def main():
    # command-line arguments
    parser = argparse.ArgumentParser(description='Train classifier on COVIDx dataset.')
    parser.add_argument('data', type=str, help='Path to COVIDx dataset')
    parser.add_argument('model', type=str, help='Path where to save the trained model and the logs. Must be a '
                                                'non-existing directory.')
    parser.add_argument('--class-weights', action='store_true', default=False,
                        help='Use class weights to compensate the dataset imbalance.')
    args = parser.parse_args()

    # prepare paths
    dataset_path = Path(args.data)
    model_path = Path(args.model)
    if model_path.is_dir():
        raise FileExistsError(str(model_path) + ' already exists')
    model_path.mkdir(parents=True)
    logs_path = model_path / 'logs'
    checkpoints_path = model_path / 'checkpoints'
    plots_path = model_path / 'training'
    model_path_no_ft = model_path / 'model_no_ft.h5'
    model_path = model_path / 'model.h5'
    checkpoints_path.mkdir()
    plots_path.mkdir()

    # build input pipeline
    train_ds = image_dataset_from_directory(dataset_path / 'train', IMAGE_SIZE)
    val_ds = image_dataset_from_directory(dataset_path / 'validation', IMAGE_SIZE, shuffle=False)
    n_classes = len(train_ds.class_indices)
    covid19_label = train_ds.class_indices['covid-19']
    class_weights = get_class_weights(train_ds) if args.class_weights else None

    # compose model
    model = ResNet50()

    # train classifier (top dense layers) and fine-tune
    loss = get_loss()
    metrics = get_metrics(n_classes, covid19_label)
    callbacks = get_callbacks(checkpoints_path, logs_path)
    history = model.fit_classifier(LR, loss, metrics, train_ds, val_ds, EPOCHS, 0, callbacks, class_weights)
    model.save_weights(str(model_path_no_ft))
    history_ft = model.fine_tune(LR_FT, loss, metrics, train_ds, val_ds, EPOCHS_FT, history.epoch[-1]+1, callbacks,
                                 FINE_TUNE_AT, class_weights)
    model.save_weights(str(model_path))
    plot_learning_curves(history, history_ft, save_path=plots_path)


if __name__ == '__main__':
    main()

# TODO (tests):
#   1) run with and without class weights, confusion matrix should improve, select the best to continue
#   2) does it over-fit? if so, add data augmentation, otherwise skip
#   3) run from scratch (without pre-trained weights), should over-fit (remember to set training=True!!!)
#   4) run without pre-trained weights but with data augmentation, over-fitting should decrease

# TODO (code):
#   1) grad-cam script
#   2) fix COVID-Net
#   3) support for training from scratch vs pre-trained weights
#   4) add data augmentation
#   5) add histogram for dataset