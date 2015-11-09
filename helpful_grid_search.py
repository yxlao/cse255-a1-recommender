from __future__ import print_function
from collections import defaultdict
import numpy as np
import scipy as sp
import cPickle as pickle
import time
from pprint import pprint
import os
import datetime

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.grid_search import GridSearchCV


# load all_data and test_data
start_time = time.time()
all_data = pickle.load(open('all_data.pickle', 'rb'))
print('data loading time:', time.time() - start_time)

# remove the outlier
for i in reversed(range(len(all_data))):
    d = all_data[i]
    if d['helpful']['outOf'] > 3000:
        all_data.pop(i)
    elif d['helpful']['outOf'] < d['helpful']['nHelpful']:
        all_data.pop(i)

# utility functions
def get_mae(helpfuls, helpfuls_predict):
    return np.mean(np.fabs(helpfuls_predict - helpfuls.astype(float)))

# load pre computed features
global_feature, users_feature, items_feature = pickle.load(
    open('global_users_items_feature.feature', 'rb'))
style_dict = pickle.load(open('style_dict.feature', 'rb'))

# feature engineering
def get_feature_time(d):
    unix_time = d['unixReviewTime']
    y, m, d = datetime.datetime.fromtimestamp(
        unix_time).strftime('%Y-%m-%d').split('-')
    y = float(y)
    m = float(m)
    d = float(d)
    return [y, m, d]

def get_feature_style(d):
    # load from style dict
    user_id = d['reviewerID']
    item_id = d['itemID']
    s = style_dict[user_id][item_id]

    feature = [s['num_words'],
               s['num_words_summary'],
               s['redability'],
               s['avg_word_len'],
               s['num_words'] /
               s['num_sentences'] if s['num_sentences'] != 0.0 else 0.0,
               s['num_unique_words'],
               s['exclam_exclam_count'] + s['question_count'],
               s['dotdotdot_count'],
               s['capital_ratio']
               ]
    return feature

def get_time_spot_ratio(times, spot):
    # return the array index ratio to insert spot
    if len(times) == 0:
        return 0.
    index = np.searchsorted(np.array(times), spot)
    return float(index) / float(len(times))

def get_feature_user(d):
    user_id = d['reviewerID']
    unix_time = d['unixReviewTime']

    s = users_feature[user_id]
    feature = [s['ratio_a'],
               s['ratio_b'],
               s['num_reviews'],
               s['avg_review_length'],
               s['avg_summary_length'],
               get_time_spot_ratio(s['review_times'], unix_time)
               ]
    return feature

def get_feature_item(d):
    item_id = d['itemID']
    unix_time = d['unixReviewTime']

    s = items_feature[item_id]
    feature = [s['ratio_a'],
               s['ratio_b'],
               s['num_reviews'],
               s['avg_review_length'],
               s['avg_summary_length'],
               get_time_spot_ratio(s['review_times'], unix_time)
               ]
    return feature

def get_feature(d):
    user_id = d['reviewerID']
    item_id = d['itemID']
    unix_time = d['unixReviewTime']

    # offset
    feature = [1.0]

    # user
    feature += get_feature_user(d)
    # item
    feature += get_feature_item(d)

    # outof
    feature += [float(d['helpful']['outOf'])]
    # rating
    feature += [float(d['rating'])]
    # styles
    feature += get_feature_style(d)
    # time
    feature += get_feature_time(d)

    return feature

# get [feature, label] from single datum
def get_feature_label_weight(d, total_outof_weights):
    # check valid
    outof = float(d['helpful']['outOf'])
    assert outof != 0.

    # feature
    feature = get_feature(d)
    # label
    ratio_label = float(d['helpful']['nHelpful']) / \
        float(d['helpful']['outOf'])
    # weight
    weight = float(d['helpful']['outOf']) / total_outof_weights

    return (feature, ratio_label, weight)

# build [feature, label] list from entire dataset
def make_dataset(train_data):
    features = []
    labels = []
    weights = []

    train_outofs = np.array([d['helpful']['outOf']
                             for d in train_data]).astype(float)
    total_outof_weights = np.sum(train_outofs)

    for d in train_data:
        if float(d['helpful']['outOf']) == 0:
            continue
        feature, label, weight = get_feature_label_weight(
            d, total_outof_weights)
        features.append(feature)
        labels.append(label)
        weights.append(weight)

    return (np.array(features), np.array(labels), np.array(weights))

# make one prediction
def predict_helpful(d, ratio_predictor):
    # ratio_predictor[func]: y = ratio_predictor(get_feature(d))

    user_id = d['reviewerID']
    item_id = d['itemID']
    outof = float(d['helpful']['outOf'])

    if (user_id in users_feature) and (item_id in items_feature):
        predict = ratio_predictor(np.array(get_feature(d)).reshape((1, -1)))
        ratio = predict[0]  # np.ndarray
    elif (user_id in users_feature) and (item_id not in items_feature):
        ratio = users_feature[user_id]['ratio_b']
    elif (user_id not in users_feature) and (item_id in items_feature):
        ratio = items_ratio[item_id]['ratio_b']
    else:
        ratio = global_feature['global_ratio_b']
    return ratio * outof

# make predictions and get mae on a dataset
def get_valid_mae(valid_data, ratio_predictor):
    # ground truth nhelpful
    helpfuls = np.array([float(d['helpful']['nHelpful']) for d in valid_data])
    # predited nhelpful
    helpfuls_predict = np.array(
        [predict_helpful(d, ratio_predictor) for d in valid_data])
    # return mae
    return get_mae(helpfuls, helpfuls_predict)

##########  Grid Search ##########

# build dataset
all_xs, all_ys, all_weights = make_dataset(all_data)
print('dataset prepared')

# call gradient boosting
print('start fitting regressor')
regressor = GradientBoostingRegressor(learning_rate=0.001,
                                      n_estimators=1000,
                                      max_depth=6,
                                      loss='lad',
                                      verbose=1)
regressor.fit(all_xs[:30000], all_ys[:30000])

print('valid set mae', get_valid_mae(all_xs[900000:], regressor_gb.predict))

# regressor.fit(all_xs, all_ys)

# # set grid search param
# param_grid = {'learning_rate': [0.02, 0.01, 0.005, 0.002, 0.001],
#               'max_depth': [3, 4, 6],
#               'min_samples_leaf': [3, 5, 9, 17],
#               'max_features': [0.8, 0.5, 0.3, 0.1]
#               }

# # init regressor
# regressor = GradientBoostingRegressor(n_estimators=3000,
#                                       subsample=0.15,
#                                       loss='lad',
#                                       verbose=1)

# # grid search
# grid_searcher = GridSearchCV(regressor, param_grid, verbose=1, n_jobs=21)
# grid_searcher.fit(train_xs, train_ys)

# # print best params
# print(grid_searcher.best_params_)


########## Produce Test ##########

# load helpful_data.json
test_data = pickle.load(open('helpful_data.pickle', 'rb'))

# on test set
test_helpfuls_predict = [
    predict_helpful(d, regressor.predict) for d in test_data]

# load 'pairs_Helpful.txt'
# get header_str and user_item_outofs
with open('pairs_Helpful.txt') as f:
    # read and strip lines
    lines = [l.strip() for l in f.readlines()]
    # stirip out the headers
    header_str = lines.pop(0)
    # get a list of user_item_ids
    user_item_outofs = [l.split('-') for l in lines]
    user_item_outofs = [[d[0], d[1], float(d[2])] for d in user_item_outofs]

# make sure `data.json` and `pairs_Helpful.txt` the same order
for (user_id, item_id, outof), d in zip(user_item_outofs, test_data):
    assert d['reviewerID'] == user_id
    assert d['itemID'] == item_id
    assert d['helpful']['outOf'] == outof

# write to output file
f = open('predictions_Helpful.txt', 'w')
print(header_str, file=f)
for (user_id, item_id, outof), helpful_predict in zip(user_item_outofs,
                                                      test_helpfuls_predict):
    print('%s-%s-%s,%s' %
          (user_id, item_id, int(outof), round(helpful_predict)), file=f)
f.close()


print('total elapsed time:', time.time() - start_time)
