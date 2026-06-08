Gryffindor = 0
Ravenclaw = 0
Hufflepuff = 0
Slytherin = 0

a = int(input('Do you like Dawn or Dusk?\n1.Dawn\n2.Dusk\nAnswer: '))

if a == 1:
    Gryffindor += 1
    Ravenclaw += 1
elif a == 2:
    Hufflepuff += 1
    Slytherin += 1
else:
    print('Wrong input')

print('\n')
    
b = int(input('When Im dead, i want people to remamber me as?\n1. The Good\n2. The Great\n3. The Wise\n4. The Bold\nAnswer: '))

if b == 1:
    Hufflepuff += 2
elif b == 2:
    Slytherin += 2
elif b == 3:
    Ravenclaw += 2
elif b == 4:
    Gryffindor += 2
else:
    print('Wrong input')

print('\n')

c = int(input('Which kind of instrument most pleases your ear?\n1.The Violin\n2. The Trumpet\n3. The Piano\n3. The Drum\nAnswer: '))

if c == 1:
    Slytherin += 4
elif c == 2:
    Hufflepuff += 4
elif c == 3:
    Ravenclaw += 4
elif c == 4:
    Gryffindor += 4
else:
    print('Wrong input')

print('\n')

if Gryffindor > 4:
    print('Welcome to Gryffindor with poin ', Gryffindor)
elif Hufflepuff > 4:
    print('Welcome to Hufflepuff with poin ', Hufflepuff)
elif Ravenclaw > 4:
    print('Welcome to Ravenclaw with poin ', Ravenclaw)
elif Slytherin > 4:
    print('Welcome to Slytherin with poin ', Slytherin)