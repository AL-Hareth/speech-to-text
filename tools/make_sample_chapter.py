"""Write a 2-page English sample chapter PDF for the end-to-end test."""
import sys

import fitz

SECTIONS = [
    ("3.1 Neural Networks", "A neural network is built from layers of neurons. Each neuron computes a weighted sum "
     "of its inputs followed by an activation function such as ReLU or sigmoid."),
    ("3.2 Backpropagation", "Backpropagation computes the gradient of the loss with respect to every weight using "
     "the chain rule. Gradient descent then updates the weights using a learning rate."),
    ("3.3 Regularization", "Regularization reduces overfitting. Dropout randomly disables neurons during training "
     "and weight decay penalises large weights."),
]

doc = fitz.open()
page, y = doc.new_page(), 60
page.insert_text((50, y), "Chapter 3: Deep Learning", fontsize=22)
y += 40
for i, (title, body) in enumerate(SECTIONS):
    if i == 2:
        page, y = doc.new_page(), 60
    page.insert_text((50, y), title, fontsize=16)
    y += 26
    for k in range(0, len(body), 85):
        page.insert_text((50, y), body[k:k + 85], fontsize=10.5)
        y += 15
    y += 20
doc.save(sys.argv[1])
