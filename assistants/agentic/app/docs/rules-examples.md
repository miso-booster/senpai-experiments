# Examples of SENSEI Rules

```yaml
name: chatbot_does_not_repeat
description: The server does not repeat answers
conversations: 1
active: True
oracle: |
  not repeated_answers(method='exact', threshold=1)
yields: f"The chatbots repeats {repeated_answers(method='exact', threshold=1)}"
# returns a list of dictionaries { step: phrase }, where phrase appears in more than one element
```

```yaml
name: chatbot_fills_all_slots
description: All conversation slots are filled
conversations: 1
active: True
oracle: data_collected()==True
yields: |
  f"Missing slots: {missing_slots()}"
```

```yaml
name: chatbot_responds_in_same_language
description: The chatbot responds in the same language
conversations: 1
active: True
oracle: responds_in_same_language()
yields: f"The chatbots does not respond in same language"
# returns a list of dictionaries { step: phrase }, where phrase appears in more than one element
```

```yaml
name: non_empty_links
description: The server does not return buttons with no links
conversations: 1
active: True
oracle: |
  not chatbot_returns("LINK: <empty>") and not chatbot_returns("AVAILABLE BUTTONS:", and_not="- BUTTON TEXT:")
# returns a list of the steps in which the chatbot returns a message with that pattern. We check that the list is empty
```

```yaml
name: chatbot_does_not_repeat
description: The server does not repeat answers
conversations: 1
active: True
oracle: |
  not repeated_answers(method='tf-idf', threshold=0.75)
yields: f"The chatbots repeats {repeated_answers(method='tf-idf', threshold=0.75)}"
# returns a list of dictionaries { step: phrase }, where phrase appears in more than one element
```

```yaml
name: geography
description: Check the capital
active: False
conversations: 1
oracle: |
  {"Spain": "Madrid", "Canada": "Ottawa", "Zambia": "Lusaka"}[country[0]] == result
yields: |
  f"Wrong result for the capital of {country[0]}, got {result}"
```

```yaml
name: division
description: Checks the operation
active: False
conversations: 1
when: operation[0]=='dividing'
oracle: abs(number1[0]/number2[0] - result) < 1e-03
yields: |
  f"Wrong result for dividing {number1} and {number2}: expected {number1[0]/number2[0]} but got {result}"
```

```yaml
name: multiplication
description: Checks the operation
active: False
conversations: 1
when: operation[0]=='multiplying'
oracle: number1[0] * number2[0] == result
yields: |
  f"Wrong result for multiplying {number1} and {number2}: expected {number1[0] * number2[0]} but got {result}"
```

```yaml
name: substraction
description: Checks the operation
active: False
conversations: 1
when: operation[0]=='substracting'
oracle: number2[0] - number1[0] == result
yields: |
  f"Wrong result for substracting {number2} and {number1}: expected {number2[0] - number1[0]} but got {result}"
```

```yaml
name: adding
description: Checks the operation
active: False
conversations: 1
when: operation[0]=='adding'
oracle: number1[0] + number2[0] == result
yields: |
  f"Wrong result for adding {number1} and {number2}: expected {number1[0] + number2[0]} but got {result}"
```

```yaml
name: multiplication
description: Checks the multiplication
active: False
conversations: 1
when: number1 is not None and number2 is not None
oracle: number1[0] * number2[0] == multiplication
yields: |
  f"Wrong result for multiplying {number1} and {number2}: expected {number1[0] * number2[0]} but got {multiplication}"
```

```yaml
name: chatbot_fills_all_slots
description: All conversation slots are filled
conversations: 1
active: True
oracle: data_collected()==True
yields: |
  f"Missing slots: {missing_slots()}"
```

```yaml
name: non_empty_links
description: The server does not return buttons with no links
conversations: 1
active: True
oracle: |
  not chatbot_returns("LINK: <empty>") and not chatbot_returns("AVAILABLE BUTTONS:", and_not="- BUTTON TEXT:")
# returns a list of the steps in which the chatbot returns a message with that pattern. We check that the list is empty
```

```yaml
name: 2_high_price
description: In two conversations, the prices are high
conversations: all
oracle: num_exist('extract_float(cost) > 50') == 4
```

```yaml
name: answers_in_english
description: The chatbot answers in english
conversations: 1
active: False
oracle: language(chatbot_phrases) == 'ENG'
```

```yaml
name: answers_tone
description: Answers do not have negative tone
conversations: 1
active: False
oracle: |
  'NEGATIVE' not in tone(chatbot_phrases)
```

```yaml
name: session_price_exact
description: A photo is 50$
active: False
conversations: 1
oracle: extract_float(cost) == 50*int(number_photo[0]) and currency(cost)=='USD'
```

```yaml
name: session_prices_different
description: Photographing more artworks costs more (assumming equal currencies)
active: False
conversations: 2
when: int(conv[0].number_photo[0]) > int(conv[1].number_photo[0])
if:   currency(conv[0].cost) == currency(conv[1].cost)
then: extract_float(conv[0].cost) > extract_float(conv[1].cost)
```

```yaml
name: session_prices_equal
description: Photographing the same number of artworks cost the same
active: False
conversations: 2
if:   conv[0].number_photo == conv[1].number_photo
then: conv[0].cost == conv[1].cost
```

```yaml
name: short_answers
description: Average chatbot answers are short (<2000 characters)
active: False
conversations: 1
oracle: length(chatbot_phrases, kind='average') < 2000
```

```yaml
name: some_high_price
description: Some of the prices are high
conversations: all
oracle: exists('extract_float(cost) > 50')
```

```yaml
name: unique_prices
description: The prices are unique
conversations: all
oracle: is_unique('cost')
```

```yaml
name: conversation_lengths
description: The number of turns of the user and the chatbot equal the conversation length
conversations: 1
active: False
oracle: conversation_length() == conversation_length('assistant') + conversation_length('user')
# 3rd param of utterance_index should be omitted
```

```yaml
name: more_toppings_cost_more
description: Adding more toppings to a custom pizza cost more
active: True
conversations: 2
when: conv[0].size == conv[1].size and conv[0].drink == conv[1].drink
if:   len(conv[0].toppings) > len(conv[1].toppings)
then: extract_float(conv[0].price) > extract_float(conv[1].price)
```

```yaml
name: only_talks_about_pizzas
description: The chatbot only talks about pizzas
conversations: 1
active: True
oracle: only_talks_about('pizza orders, drink orders, information on delivery of pizzas, information about the pizza shop')
# 2nd and 3rd params of only_talks_about should be ommited
```

```yaml
name: ordering_conversation_turns
description: The user always orders a pizza and then drinks
conversations: 1
active: False
oracle: utterance_index('user', 'ordering a pizza') < utterance_index('user', 'ordering drink')
# 3rd param of utterance_index should be omitted
```

```yaml
name: ordering_conversation_turns_assistant
description: The assistant confirms the pizza order after the user orders a pizza
conversations: 1
active: False
oracle: utterance_index('user', 'ordering a pizza') < utterance_index('assistant', 'confirms pizza order')
# 3rd param of utterance_index should be omitted
```

```yaml
name: same_number_of_toopings_cost_the_same
description: Pizzas with same number of toppings cost the same
conversations: 2
active: False
when: conv[0].drink == conv[1].drink
if: conv[0].size == conv[1].size and len(conv[0].toppings)==len(conv[1].toppings)
then: extract_float(conv[0].price) == extract_float(conv[1].price)
```

```yaml
name: small_pizza_price
description: Checks the base prices of small pizzas (>=10$)
active: True
conversations: 1
when: size[0] == 'small'
oracle: extract_float(price) >= 104 and currency(price)=='USD'
yields: f"Wrong price for small pizzas, it should be (>=10$)"
```

```yaml
name: topping_prices
description: More toppings on a pizza cost more
conversations: 2
active: False
when: conv[0].size == conv[1].size
if:   len(conv[0].toppings) > len(conv[1].toppings)
then: conv[0].steps == conv[1].steps
# set(conv[0].size) == set(conv[1].size)
# set(['small']) == set(['small'])
```

```yaml
name: toppings_for_small_pizzas
description: Small pizzas should have less than 3 toppings
conversations: 1
active: False
if: |
  'small' in size
then: len(toppings)>3
```

```yaml
name: unknown_toppings_are_rejected
description: Unknown toppings are rejected
conversations: 1
active: False
if: not all(elem in ['cheese', 'mushrooms', 'pepper', 'ham', 'bacon', 'pepperoni', 'olives', 'corn', 'chicken'] for elem in toppings)
then: utterance_index('assistant', 'some of the toppings requested by the user are not valid')>0
```

```yaml
name: wrong_toppings_for_large_pizzas
description: Large pizzas should have more than 3 toppings
conversations: 1
active: False
if: |
  'small' in size
then: len(toppings)>13
```
