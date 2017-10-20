import os
import pickle
import io
import bson
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score
from PIL import Image
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.autograd import Variable
from models.resnet import *
from torchvision import transforms

# writes loss to file
def write_loss(loss, acc):
    w = '{}, {}\n'.format(format(loss, '.3f'), format(acc, '.2f'))
    with open('exp2_loss.txt', 'a') as f:
        f.write(w)

def batch_generator(data_path, size=130, batch_size=32, return_labels=True):

    # preprocessing pipeline
    process = transforms.Compose([
        transforms.Scale(size),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        lambda x: x.cuda().view(1,3,size,size),
        transforms.Normalize(mean=[.485, .456, .406],
                             std=[.229, .224, .225])
        ])
    
    # decode data
    data = bson.decode_file_iter(open(data_path, 'rb'))

    # iterate over data items
    x = torch.FloatTensor(()).cuda()
    y = torch.LongTensor(()).cuda()
    for item in data:

        # get item label
        category = item.get('category_id', '')
        label = int(labelencoder.transform([category])) if category else 0
        label = torch.LongTensor([label]).cuda()

        # get images in item and process
        for image in item.get('imgs'):

            # from binary, process, augment and to tensor
            proc_img = process(Image.open(io.BytesIO(image.get('picture', None))))

            # add to batch
            x = torch.cat([x, proc_img])
            y = torch.cat([y, label])

            if x.size(0) == batch_size:

                if return_labels:
                    yield Variable(x), Variable(y)
                else:
                    yield Variable(x)
                
                x = torch.FloatTensor(()).cuda()
                y = torch.LongTensor(()).cuda()

def train(epoch):

    # init stats
    c = 0
    train_loss = 0
    train_acc = 0

    # set model to train mode and reset gradients
    model.train()
    optimizer.zero_grad()
    
    # iterate over training batches
    for batch_idx, (x, y) in enumerate(data_loader):

        # get batch predictions and loss
        output = model(x)
        loss = crit(output, y)
        
        # accumulate gradients
        loss.backward()
        if batch_idx % accum_iter == 0:
            optimizer.step()
            optimizer.zero_grad()

        # accumulate statistics
        _, idx = output.cpu().max(1)
        train_loss += loss.data[0]
        train_acc += accuracy_score(y.cpu().data.numpy(), idx.data.numpy().ravel())
        c += 1

        # print statistics
        if batch_idx % print_iter == 0:

            # get average loss and accuracy
            train_loss /= c
            train_acc /= c

            # save loss and acc to file
            write_loss(train_loss, train_acc)

            # print the statistics
            print('\rEpoch {} [{}/{} ({:.0f}%)] - loss: {:.6f} - acc: {:.3f}'.format(
                epoch+1, batch_idx * batch_size, 7069896, 100. * batch_idx / (7069896//batch_size), 
                train_loss, train_acc), end='')
            
            # reset stats
            c = 0
            train_loss = 0
            train_acc = 0

        # exit training phase
        if batch_idx >= val_split:
            return

def test():

    # init stats
    test_loss = 0
    correct = 0

    # set model to evaluation mode
    model.eval()

    # iterate over validation batches
    for batch_idx, (x, y) in enumerate(data_loader):

        # forward pass plus stat accumulation
        output = model(x)
        test_loss += crit(output, y).data[0]
        pred = output.data.max(1)[1]
        correct += pred.eq(y.data.view_as(pred)).cpu().sum()

    # print validation phase statistics
    test_loss /= (batch_idx + 1)
    print('\nValidation set - loss: {:.4f} - val-acc: {:.0f}%\n'.format(
        test_loss, (correct / ((batch_idx + 1) * batch_size))*100))


# load lookup table and labelencoder
with open('../data/labelencoder.pkl', 'rb') as f:
    labelencoder = pickle.load(f)
categories = pd.read_csv('../data/categories.csv')

# parameters
batch_size = 32
learning_rate = 1e-3
epochs = 3
num_classes = len(labelencoder.classes_)
val_split = round(0.9*(7069896//batch_size))
accum_iter = 8
print_iter = 10

# load ResNet50 without ImageNet weights
model = resnet50(pretrained=False)

# freeze all parameters
for param in model.parameters():
    param.requires_grad = False
model.fc = nn.Linear(2048, 5270)

# load pre-trained Cdiscount weights
model.load_state_dict(torch.load('resnet50_2ep_finetuneClf.pth'))

# unfreeze fully-connected and 3rd/4th layer
for param in model.layer4.parameters():
    param.requires_grad = True
for param in model.layer3.parameters():
    param.requires_grad = True

# send model to GPU
model.cuda()

# loss and optimizer
crit = nn.CrossEntropyLoss()
optimizer = optim.SGD(filter(lambda p: p.requires_grad, model.parameters()), 
                      lr=learning_rate, momentum=0.9, weight_decay=5e-4)

# train the model
for e in range(epochs):
    data_loader = batch_generator('../data/train.bson', batch_size=batch_size)
    train(e)
    test()
    torch.save(model.state_dict(), './resnet50_{}-epoch_finetune-fc-lyr3-lyr4.pth'.format(e+1))

print('\nFinished.')
