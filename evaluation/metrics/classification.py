"""Multiclass precision, recall, and F1 for labeled predictions (e.g. gap assessments)."""


def _label_set(labels):
    return list(dict.fromkeys(labels))


def confusion_counts(y_true, y_pred, labels):
    """Per-label true positive, false positive, false negative counts."""
    counts = {label: {'tp': 0, 'fp': 0, 'fn': 0} for label in labels}
    for truth, pred in zip(y_true, y_pred, strict=True):
        for label in labels:
            if truth == label and pred == label:
                counts[label]['tp'] += 1
            elif pred == label and truth != label:
                counts[label]['fp'] += 1
            elif truth == label and pred != label:
                counts[label]['fn'] += 1
    return counts


def _safe_div(num, den):
    return num / den if den else 0.0


def precision_recall_f1(y_true, y_pred, labels=None):
    """Macro-averaged precision, recall, and F1 plus per-label scores."""
    if len(y_true) != len(y_pred):
        raise ValueError('y_true and y_pred must have the same length')
    if not y_true:
        return {'macro': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0}, 'per_label': {}, 'support': 0}
    labels = _label_set(labels or list(y_true) + list(y_pred))
    counts = confusion_counts(y_true, y_pred, labels)
    per_label = {}
    macro_p, macro_r, macro_f, used = 0.0, 0.0, 0.0, 0
    for label in labels:
        tp, fp, fn = counts[label]['tp'], counts[label]['fp'], counts[label]['fn']
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        support = tp + fn
        per_label[label] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': support}
        if support:
            macro_p += precision
            macro_r += recall
            macro_f += f1
            used += 1
    macro_div = used or 1
    return {
        'macro': {
            'precision': macro_p / macro_div,
            'recall': macro_r / macro_div,
            'f1': macro_f / macro_div,
        },
        'per_label': per_label,
        'support': len(y_true),
    }


def micro_precision_recall_f1(y_true, y_pred, labels=None):
    """Micro-averaged scores from pooled TP/FP/FN."""
    if len(y_true) != len(y_pred):
        raise ValueError('y_true and y_pred must have the same length')
    labels = _label_set(labels or list(y_true) + list(y_pred))
    counts = confusion_counts(y_true, y_pred, labels)
    tp = sum(c['tp'] for c in counts.values())
    fp = sum(c['fp'] for c in counts.values())
    fn = sum(c['fn'] for c in counts.values())
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {'precision': precision, 'recall': recall, 'f1': f1, 'support': len(y_true)}
