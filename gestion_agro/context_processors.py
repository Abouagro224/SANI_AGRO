from .models import Notification

def notifications_non_lues(request):
    if request.user.is_authenticated:
        # On compte les vraies notifications non lues du producteur connecté
        notif_count = Notification.objects.filter(destinataire=request.user, lu=False).count()
        # On récupère les 5 dernières pour le menu déroulant
        dernieres_notifs = Notification.objects.filter(destinataire=request.user, lu=False).order_by('-date_creation')[:5]
        return {
            'notif_count': notif_count,
            'dernieres_notifs': dernieres_notifs
        }
    return {'notif_count': 0, 'dernieres_notifs': []}