import logging
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.db.models.deletion import ProtectedError
from .deletion_context import is_policydevice_delete_allowed

from .models import Action, Policy, PolicyDevice

logger = logging.getLogger(__name__)

@receiver(pre_delete, sender=Policy)
def prevent_policy_delete_if_applied(sender, instance: Policy, **kwargs):
    """
    Prevent deleting a Policy when it's applied to any device.
    We'll check related PolicyDevice rows and call is_applied() on each.
    """
    applied_pds = []
    
    for pd in instance.policy_devices.select_related('device').all():
        try:
            if pd.is_applied():
                applied_pds.append(pd)
        except Exception as exc:
            # if we can't determine the state, assume it's applied
            logger.exception("Error evaluating is_applied() for PolicyDevice %s (policy=%s): %s", getattr(pd, "pk", None), getattr(instance, "pk", None), exc)
            applied_pds.append(pd)
    
    if applied_pds:
        raise ProtectedError(
            f"Cannot delete Policy '{instance.name}' because it is applied on one or more devices.",
            applied_pds
        )
        
@receiver(pre_delete, sender=PolicyDevice)
def prevent_policydevice_delete_if_applied(sender, instance: PolicyDevice, **kwargs):
    """
    Prevent deleting a PolicyDevice if it is applied,
    except when we intentionally delete a whole Device.
    """

    # Device deletion cleanup is allowed to remove PolicyDevice rows
    if is_policydevice_delete_allowed():
        return

    try:
        if instance.is_applied():
            raise ProtectedError(
                "This PolicyDevice is applied on the device; cannot delete.",
                [instance]
            )
    except ProtectedError:
        raise
    except Exception as exc:
        logger.exception(
            "Error evaluating is_applied() for PolicyDevice %s: %s",
            getattr(instance, "pk", None),
            exc
        )
        raise ProtectedError(
            "Unable to determine apply state; refusing delete.",
            [instance]
        )

@receiver(pre_delete, sender=Action)
def prevent_non_deletable_action_delete(sender, instance: Action, **kwargs):
    """
    Prevent deleting non-deletable system/main actions.
    """
    if not instance.is_deletable:
        raise ProtectedError("This action is a main action and is not deletable.", [instance])