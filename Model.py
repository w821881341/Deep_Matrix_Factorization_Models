# -*- Encoding:UTF-8 -*-

import tensorflow as tf
import numpy as np
import argparse
from DataSet import DataSet
import sys
import os
import heapq
import math


def main():
    parser = argparse.ArgumentParser(description="Options")

    parser.add_argument('-dataName', action='store', dest='dataName', default='ml-1m')
    parser.add_argument('-negNum', action='store', dest='negNum', default=7, type=int)
    parser.add_argument('-lambda_value', action='store', dest='lambda_value',type=float, default=1)

    parser.add_argument('-userAutoRec', action='store', dest='userAutoRec', default=[500])
    parser.add_argument('-itemAutoRec', action='store', dest='itemAutoRec', default=[500])
    parser.add_argument('-userLayer', action='store', dest='userLayer', default=[512, 64])
    parser.add_argument('-itemLayer', action='store', dest='itemLayer', default=[1024, 64])
    # parser.add_argument('-reg', action='store', dest='reg', default=1e-3)
    parser.add_argument('-lr', action='store', dest='lr', default=0.0001)
    parser.add_argument('-maxEpochs', action='store', dest='maxEpochs', default=50, type=int)
    parser.add_argument('-batchSize', action='store', dest='batchSize', default=256, type=int)
    parser.add_argument('-earlyStop', action='store', dest='earlyStop', default=5)
    parser.add_argument('-checkPoint', action='store', dest='checkPoint', default='./checkPoint/')
    parser.add_argument('-topK', action='store', dest='topK', default=10)


    args = parser.parse_args()

    classifier = Model(args)

    classifier.run()


class Model:
    def __init__(self, args):
        self.dataName = args.dataName
        self.dataSet = DataSet(self.dataName)
        self.shape = self.dataSet.shape
        self.maxRate = self.dataSet.maxRate

        self.train = self.dataSet.train
        self.test = self.dataSet.test

        self.negNum = args.negNum
        self.lambda_value = args.lambda_value
        self.testNeg = self.dataSet.getTestNeg(self.test, 99)
        self.add_embedding_matrix()

        self.add_placeholders()

        self.userLayer = args.userLayer
        self.itemLayer = args.itemLayer

        self.userAutoRec = args.userAutoRec
        self.itemAutoRec = args.itemAutoRec

        self.add_model()

        self.add_loss()
        self.add_cost()

        self.lr = args.lr
        self.add_train_step()

        self.checkPoint = args.checkPoint
        self.init_sess()

        self.maxEpochs = args.maxEpochs
        self.batchSize = args.batchSize

        self.topK = args.topK
        self.earlyStop = args.earlyStop



    def add_placeholders(self):
        self.user = tf.placeholder(tf.int32)
        self.item = tf.placeholder(tf.int32)
        self.rate = tf.placeholder(tf.float32)
        self.drop = tf.placeholder(tf.float32)

    def add_embedding_matrix(self):
        self.user_item_embedding = tf.convert_to_tensor(self.dataSet.getEmbedding())
        self.item_user_embedding = tf.transpose(self.user_item_embedding)

    def add_model(self):
        self.user_input = tf.nn.embedding_lookup(self.user_item_embedding, self.user)
        self.item_input = tf.nn.embedding_lookup(self.item_user_embedding, self.item)

        def init_variable(shape, name):
            return tf.Variable(tf.truncated_normal(shape=shape, dtype=tf.float32, stddev=0.01), name=name)

        with tf.name_scope("User_Encoder"):
            self.user_V = init_variable([self.shape[1],self.userAutoRec[0]],"User_V")
            self.user_W = init_variable([self.userAutoRec[0],self.shape[1]], "User_W")
            self.user_mu = init_variable([self.userAutoRec[0]], "User_mu")
            self.user_b = init_variable([self.shape[1]], "User_b")
            user_pre_Encoder = tf.matmul(self.user_input,self.user_V)+self.user_mu
            self.user_Encoder = tf.nn.sigmoid(user_pre_Encoder)
            user_pre_Decoder = tf.matmul(self.user_Encoder, self.user_W) + self.user_b
            self.user_Decoder = tf.identity(user_pre_Decoder)

        with tf.name_scope("Item_Encoder"):
            self.item_V = init_variable([self.shape[0],self.itemAutoRec[0]],"Item_V")
            self.item_W = init_variable([self.itemAutoRec[0],self.shape[0]], "Item_W")
            self.item_mu = init_variable([self.itemAutoRec[0]], "Item_mu")
            self.item_b = init_variable([self.shape[0]], "Item_b")
            item_pre_Encoder = tf.matmul(self.item_input,self.item_V)+self.item_mu
            self.item_Encoder = tf.nn.sigmoid(item_pre_Encoder)
            item_pre_Decoder = tf.matmul(self.item_Encoder, self.item_W) + self.item_b
            self.item_Decoder = tf.identity(item_pre_Decoder)


        with tf.name_scope("User_Layer"):
            user_W1 = init_variable([self.userAutoRec[0], self.userLayer[0]], "user_W1")
            user_out = tf.matmul(self.user_Encoder, user_W1)
            for i in range(0, len(self.userLayer)-1):
                W = init_variable([self.userLayer[i], self.userLayer[i+1]], "user_W"+str(i+2))
                b = init_variable([self.userLayer[i+1]], "user_b"+str(i+2))
                user_out = tf.nn.relu(tf.add(tf.matmul(user_out, W), b))

        with tf.name_scope("Item_Layer"):
            item_W1 = init_variable([self.itemAutoRec[0], self.itemLayer[0]], "item_W1")
            item_out = tf.matmul(self.item_Encoder, item_W1)
            for i in range(0, len(self.itemLayer)-1):
                W = init_variable([self.itemLayer[i], self.itemLayer[i+1]], "item_W"+str(i+2))
                b = init_variable([self.itemLayer[i+1]], "item_b"+str(i+2))
                item_out = tf.nn.relu(tf.add(tf.matmul(item_out, W), b))

        norm_user_output = tf.sqrt(tf.reduce_sum(tf.square(user_out), axis=1))
        norm_item_output = tf.sqrt(tf.reduce_sum(tf.square(item_out), axis=1))
        self.y_ = tf.reduce_sum(tf.multiply(user_out, item_out), axis=1, keep_dims=False) / (norm_item_output* norm_user_output)
        self.y_ = tf.maximum(1e-6, self.y_)

    def add_loss(self):
        regRate = self.rate / self.maxRate
        losses = regRate * tf.log(self.y_) + (1 - regRate) * tf.log(1 - self.y_)
        loss = -tf.reduce_sum(losses)
        # regLoss = tf.add_n([tf.nn.l2_loss(v) for v in tf.trainable_variables()])
        # self.loss = loss + self.reg * regLoss
        self.loss = loss

    def add_cost(self):

        user_pre_rec_cost = self.user_input - self.user_Decoder
        user_rec_cost = tf.square(self.l2_norm(user_pre_rec_cost))
        user_pre_reg_cost = tf.square(self.l2_norm(self.user_W)) + tf.square(self.l2_norm(self.user_V))
        user_reg_cost = self.lambda_value * 0.5 * user_pre_reg_cost
        
        item_pre_rec_cost = self.item_input - self.item_Decoder
        item_rec_cost = tf.square(self.l2_norm(item_pre_rec_cost))
        item_pre_reg_cost = tf.square(self.l2_norm(self.item_W)) + tf.square(self.l2_norm(self.item_V))
        item_reg_cost = self.lambda_value * 0.5 * item_pre_reg_cost

        self.cost = 0.5 * (user_rec_cost + user_reg_cost+item_rec_cost+item_reg_cost)

    def add_train_step(self):
        '''
        global_step = tf.Variable(0, name='global_step', trainable=False)
        self.lr = tf.train.exponential_decay(self.lr, global_step,
                                             self.decay_steps, self.decay_rate, staircase=True)
        '''
        optimizer = tf.train.AdamOptimizer(float(self.lr))
        self.train_step = optimizer.minimize(self.loss)

    def init_sess(self):
        self.config = tf.ConfigProto()
        self.config.gpu_options.allow_growth = True
        self.config.allow_soft_placement = True
        self.sess = tf.Session(config=self.config)
        self.sess.run(tf.global_variables_initializer())

        self.saver = tf.train.Saver()
        if os.path.exists(self.checkPoint):
            [os.remove(f) for f in os.listdir(self.checkPoint)]
        else:
            os.mkdir(self.checkPoint)

    def run(self):
        best_hr = -1
        best_NDCG = -1
        best_epoch = -1
        print("Start Training!")
        for epoch in range(self.maxEpochs):
            print("="*20+"Epoch ", epoch, "="*20)
            self.run_epoch(self.sess)
            print('='*50)
            print("Start Evaluation!")
            hr, NDCG = self.evaluate(self.sess, self.topK)
            print("Epoch ", epoch, "HR: {}, NDCG: {}".format(hr, NDCG))
            if hr > best_hr or NDCG > best_NDCG:
                best_hr = hr
                best_NDCG = NDCG
                best_epoch = epoch
                self.saver.save(self.sess, self.checkPoint)
            if epoch - best_epoch > self.earlyStop:
                print("Normal Early stop!")
                break
            print("="*20+"Epoch ", epoch, "End"+"="*20)
        print("Best hr: {}, NDCG: {}, At Epoch {}".format(best_hr, best_NDCG, best_epoch))
        print("Training complete!")

    def run_epoch(self, sess, verbose=10):
        train_u, train_i, train_r = self.dataSet.getInstances(self.train, self.negNum)
        train_len = len(train_u)
        shuffled_idx = np.random.permutation(np.arange(train_len))
        train_u = train_u[shuffled_idx]
        train_i = train_i[shuffled_idx]
        train_r = train_r[shuffled_idx]

        num_batches = len(train_u) // self.batchSize + 1

        losses = []
        costs = []
        for i in range(num_batches):
            min_idx = i * self.batchSize
            max_idx = np.min([train_len, (i+1)*self.batchSize])
            train_u_batch = train_u[min_idx: max_idx]
            train_i_batch = train_i[min_idx: max_idx]
            train_r_batch = train_r[min_idx: max_idx]

            feed_dict = self.create_feed_dict(train_u_batch, train_i_batch, train_r_batch)
            _, tmp_loss, tmp_cost = sess.run([self.train_step, self.loss, self.cost], feed_dict=feed_dict)
            losses.append(tmp_loss)
            costs.append(tmp_cost)
            if verbose and i % verbose == 0:
                sys.stdout.write('\r{} / {} : loss = {} / cost = {}'.format(
                    i, num_batches, np.mean(losses[-verbose:]), 0.0001*np.mean(costs[-verbose:])
                ))
                sys.stdout.flush()
        loss = np.mean(losses) + 0.0001 * np.mean(costs)
        print("\nMean loss+cost in this epoch is: {}".format(loss))
        return loss

    def create_feed_dict(self, u, i, r=None, drop=None):
        return {self.user: u,
                self.item: i,
                self.rate: r,
                self.drop: drop}

    def l2_norm(self,tensor):
        return tf.sqrt(tf.reduce_sum(tf.square(tensor)))

    def evaluate(self, sess, topK):
        def getHitRatio(ranklist, targetItem):
            for item in ranklist:
                if item == targetItem:
                    return 1
            return 0
        def getNDCG(ranklist, targetItem):
            for i in range(len(ranklist)):
                item = ranklist[i]
                if item == targetItem:
                    return math.log(2) / math.log(i+2)
            return 0



        hr =[]
        NDCG = []
        testUser = self.testNeg[0]
        testItem = self.testNeg[1]
        for i in range(len(testUser)):
            target = testItem[i][0]
            feed_dict = self.create_feed_dict(testUser[i], testItem[i])
            predict = sess.run(self.y_, feed_dict=feed_dict)

            item_score_dict = {}

            for j in range(len(testItem[i])):
                item = testItem[i][j]
                item_score_dict[item] = predict[j]

            ranklist = heapq.nlargest(topK, item_score_dict, key=item_score_dict.get)

            tmp_hr = getHitRatio(ranklist, target)
            tmp_NDCG = getNDCG(ranklist, target)
            hr.append(tmp_hr)
            NDCG.append(tmp_NDCG)
        return np.mean(hr), np.mean(NDCG)

if __name__ == '__main__':
    main()
