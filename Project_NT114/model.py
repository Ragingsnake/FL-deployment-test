import torch
import torch.nn as nn
import torch.nn.functional as F

class CNN(nn.Module):
    def __init__(self, num_classes=62):
        super(CNN, self).__init__()
        self.conv1 = nn.Conv2d(1, 48, kernel_size=5, padding=2)
        self.bn1 = nn.BatchNorm2d(48)
        self.conv2 = nn.Conv2d(48, 96, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(96)
        self.conv3 = nn.Conv2d(96, 192, kernel_size=5, padding=2)
        self.bn3 = nn.BatchNorm2d(192)
        self.dropout1 = nn.Dropout2d(0.25)
        self.dropout2 = nn.Dropout(0.5)

        dummy = torch.zeros(1, 1, 28, 28)
        dummy = self._forward_conv(dummy)
        flatten_size = dummy.view(1, -1).size(1)
        self.flatten_size = flatten_size

        self.fc1 = nn.Linear(self.flatten_size, 512)
        self.fc2 = nn.Linear(512, num_classes)

    def _forward_conv(self, x):
        x = self.bn1(F.relu(self.conv1(x)))
        x = F.max_pool2d(x, 2)
        x = self.bn2(F.relu(self.conv2(x)))
        x = F.max_pool2d(x, 2)
        x = self.bn3(F.relu(self.conv3(x)))
        x = F.max_pool2d(x, 2)
        x = self.dropout1(x)
        return x

    def forward(self, x):
        x = self._forward_conv(x)
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        x = self.dropout2(x)
        x = self.fc2(x)
        return x