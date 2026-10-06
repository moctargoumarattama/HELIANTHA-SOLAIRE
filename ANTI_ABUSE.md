# Protection anti-abus

Les calculs de devis restent illimités. Leurs notifications WhatsApp sont mises
en file puis envoyées en arrière-plan. Chaque destinataire bénéficie d'un délai
de 20 secondes entre deux tentatives d'envoi ; pendant ce délai, la file conserve
le dernier devis en attente. Le cache du délai expire après 60 secondes.

Les deux routes de l'assistant (`/api/assistant/chat` et
`/api/assistant/chat/stream`) partagent un quota de 30 messages par fenêtre
glissante de 10 minutes et par IP. Le dépassement renvoie un message courtois
avec un en-tête `Retry-After`. Ces protections en mémoire sont propres à chaque
processus.

Par défaut, l'IP vient de la connexion au serveur. Si Flask est accessible
uniquement derrière un proxy de confiance, définir `TRUSTED_PROXY_HOPS=1`
pour un seul proxy, ou le nombre exact de proxies traversés. Le proxy doit
remplacer l'en-tête `X-Forwarded-For` reçu du client. Laisser cette option à
`0` pour un serveur directement accessible.
